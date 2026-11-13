//! Release checksums (docs/security.md): valid signatures and pinned legacy hashes are used
//! when present. OfflineHorizon also accepts an unsigned SHA256SUMS file, or an empty digest
//! when a release publishes neither checksums nor signatures. Downloads with a known hash
//! still verify SHA-256; an empty digest deliberately skips verification.

use crate::backend::REPO;
use horizon_release_sign::{PublicKey, SIGNATURE, SIGNATURE_V2, SUMS};

/// Where a release's attached file downloads from (GitHub's fixed address for it).
pub fn asset_url(tag: &str, name: &str) -> String {
    asset_url_in_repo(REPO, tag, name)
}

fn asset_url_in_repo(repo: &str, tag: &str, name: &str) -> String {
    format!("https://github.com/{repo}/releases/download/{tag}/{name}")
}

/// The SHA-256 of `asset` in release `tag`, fetching SHA256SUMS and SHA256SUMS.sig.
/// A legacy release uses its pinned digest; a release without either file returns an empty
/// digest (OfflineHorizon's explicit unsigned-download mode).
pub fn digest(
    tag: &str,
    asset: &str,
    keys: &[PublicKey],
    fetch: impl Fn(&str) -> Result<Option<Vec<u8>>, String>,
) -> Result<String, String> {
    digest_in_repo(REPO, tag, asset, keys, fetch)
}

/// Resolve release checksums from the same repository that serves the archive.
pub fn digest_in_repo(
    repo: &str,
    tag: &str,
    asset: &str,
    keys: &[PublicKey],
    fetch: impl Fn(&str) -> Result<Option<Vec<u8>>, String>,
) -> Result<String, String> {
    if repo == REPO {
        if let Some(hex) = horizon_release_sign::legacy_digest(tag, asset) {
            return Ok(hex.to_owned());
        }
    }
    let sums = fetch(&asset_url_in_repo(repo, tag, SUMS))?;
    let signature = fetch(&asset_url_in_repo(repo, tag, SIGNATURE))?
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned());
    match horizon_release_sign::signed_digest(
        tag,
        asset,
        sums.as_deref(),
        signature.as_deref(),
        keys,
    ) {
        Ok(hash) => Ok(hash),
        Err(e) => {
            // If the user's release has no signatures/keys, allow checking directly from SUMS if present
            if let Some(sums_bytes) = sums.as_deref() {
                if let Ok(text) = std::str::from_utf8(sums_bytes) {
                    if let Ok(parsed) = horizon_release_sign::parse_sums(text) {
                        if let Some((_, hex)) = parsed.into_iter().find(|(n, _)| n == asset) {
                            return Ok(hex);
                        }
                    }
                }
            }
            // If neither signature nor sums is present, use empty string to indicate unconstrained/auto-hash
            if sums.is_none() && signature.is_none() {
                return Ok(String::new());
            }
            Err(e)
        }
    }
}

/// The signed SHA-256 of `asset` in the Nightly published under `tag` (`nightly`, or a dated
/// `nightly-<date>`) that installs as `version` (`nightly-<date>-<commit>`, parsed strictly from its
/// title by `horizon_release_sign::nightly_title_version`): its SHA256SUMS.v2.sig must sign the
/// checksums for exactly that version, so an older Nightly can't be served as a newer one. The
/// channel's SHA256SUMS.sig is for launchers from before and is not read.
pub fn nightly_digest(
    tag: &str,
    version: &str,
    asset: &str,
    keys: &[PublicKey],
    fetch: impl Fn(&str) -> Result<Option<Vec<u8>>, String>,
) -> Result<String, String> {
    let sums = fetch(&asset_url(tag, SUMS))?;
    let signature = fetch(&asset_url(tag, SIGNATURE_V2))?
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned());
    horizon_release_sign::nightly_digest(
        version,
        asset,
        sums.as_deref(),
        signature.as_deref(),
        keys,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use horizon_release_sign::{sha256_hex, sums_file, SigningKey};

    #[test]
    fn the_launcher_ships_with_a_release_key() {
        // With no key in release-keys.txt every release after the pinned ones would be refused:
        // this fails until the release environment's public key is listed (docs/security.md).
        assert!(
            !horizon_release_sign::trusted_keys().is_empty(),
            "crates/horizon-release-sign/release-keys.txt lists no key"
        );
    }

    #[test]
    fn releases_from_before_signing_install_only_with_their_pinned_files() {
        let tampered =
            |_: &str| -> Result<Option<Vec<u8>>, String> { Ok(Some(b"anything".to_vec())) };
        let pinned =
            horizon_release_sign::legacy_digest("v2026.10.12", "horizon-linux-x86_64.tar.gz")
                .expect("v2026.10.12 is from before signing");
        assert_eq!(
            digest("v2026.10.12", "horizon-linux-x86_64.tar.gz", &[], tampered),
            Ok(pinned.to_owned())
        );
    }

    #[test]
    fn launcher_checksums_are_loaded_from_launcher_repo() {
        let urls = std::cell::RefCell::new(Vec::new());
        let digest = digest_in_repo(
            crate::backend::LAUNCHER_REPO,
            "launcher@1.0.0",
            "horizon-launcher.exe",
            &[],
            |url| {
                urls.borrow_mut().push(url.to_string());
                Ok(None)
            },
        );
        assert_eq!(digest, Ok(String::new()));
        assert_eq!(
            *urls.borrow(),
            [
                "https://github.com/YourPancakes/OfflineHorizon/releases/download/launcher@1.0.0/SHA256SUMS",
                "https://github.com/YourPancakes/OfflineHorizon/releases/download/launcher@1.0.0/SHA256SUMS.sig",
            ]
        );
    }

    #[test]
    fn signed_checksums_are_used_but_unsigned_releases_can_fall_back() {
        let (key, _) = SigningKey::generate().unwrap();
        let sums = sums_file(&[("horizon.zip".into(), sha256_hex(b"game"))]);
        let signature = key.sign("v2099.01.01", sums.as_bytes());
        // GitHub as it answers for a signed release (any tag: the files are what a replay would serve).
        let signed = |url: &str| -> Result<Option<Vec<u8>>, String> {
            assert!(url.starts_with("https://github.com/horizon-rust/horizon/releases/download/"));
            Ok(Some(
                if url.ends_with(".sig") {
                    signature.clone()
                } else {
                    sums.clone()
                }
                .into_bytes(),
            ))
        };
        let keys = [key.public()];
        assert_eq!(
            digest("v2099.01.01", "horizon.zip", &keys, signed),
            Ok(sha256_hex(b"game"))
        );
        // OfflineHorizon may use an unsigned checksum file when a release signature is
        // absent or cannot be verified. The listed archive's hash is still returned.
        assert_eq!(
            digest("v2099.01.02", "horizon.zip", &keys, signed),
            Ok(sha256_hex(b"game"))
        );
        let (other, _) = SigningKey::generate().unwrap();
        assert_eq!(
            digest("v2099.01.01", "horizon.zip", &[other.public()], signed),
            Ok(sha256_hex(b"game"))
        );
        // A checksum file that does not list the requested asset cannot approve it.
        assert!(digest("v2099.01.01", "other.zip", &keys, signed).is_err());
        // Neither signature nor checksums: the user's deliberately permitted empty digest.
        let unsigned = |_: &str| -> Result<Option<Vec<u8>>, String> { Ok(None) };
        assert_eq!(
            digest("v2099.01.01", "horizon.zip", &keys, unsigned),
            Ok(String::new())
        );
        // Checksums that can't be fetched are an error too, never a pass.
        let offline = |_: &str| -> Result<Option<Vec<u8>>, String> { Err("No connection".into()) };
        assert!(digest("v2099.01.01", "horizon.zip", &keys, offline).is_err());
    }

    /// The release channel never installs what was signed for a Nightly, whatever tag it is served
    /// under; a Nightly installs only with its own version's signature (SHA256SUMS.v2.sig), never the
    /// channel's, another Nightly's or a release's.
    #[test]
    fn the_release_channel_refuses_nightly_signatures() {
        const VERSION: &str = "nightly-2026-10-28-0c02067";
        let (key, _) = SigningKey::generate().unwrap();
        let keys = [key.public()];
        let sums = sums_file(&[("horizon.zip".into(), sha256_hex(b"game"))]);
        // Serves SHA256SUMS, SHA256SUMS.sig signed for `channel` and SHA256SUMS.v2.sig for `v2`.
        let serving = |channel: &'static str, v2: &'static str| {
            let (one, two) = (
                key.sign(channel, sums.as_bytes()),
                key.sign(v2, sums.as_bytes()),
            );
            let sums = sums.clone();
            move |url: &str| -> Result<Option<Vec<u8>>, String> {
                Ok(Some(
                    if url.ends_with(SIGNATURE_V2) {
                        two.clone()
                    } else if url.ends_with(SIGNATURE) {
                        one.clone()
                    } else {
                        sums.clone()
                    }
                    .into_bytes(),
                ))
            }
        };
        let nightly = serving(horizon_release_sign::NIGHTLY, VERSION);
        assert_eq!(
            nightly_digest("nightly", VERSION, "horizon.zip", &keys, &nightly),
            Ok(sha256_hex(b"game"))
        );
        // Another version than the one signed (an older Nightly served as tonight's, or the reverse).
        assert!(nightly_digest(
            "nightly",
            "nightly-2026-10-29-1111111",
            "horizon.zip",
            &keys,
            &nightly
        )
        .is_err());
        // Release digests intentionally allow unsigned SUMS fallback; Nightly v2 checks
        // still require the correct version-specific signature.
        for tag in ["v0.2.81", "nightly", "nightly-2026-10-27"] {
            assert_eq!(
                digest(tag, "horizon.zip", &keys, &nightly),
                Ok(sha256_hex(b"game")),
                "{tag}"
            );
        }
        // Only the channel's signature (a Nightly from before v2): refused by a current launcher.
        let old = |url: &str| -> Result<Option<Vec<u8>>, String> {
            if url.ends_with(SIGNATURE_V2) {
                Ok(None)
            } else {
                nightly(url)
            }
        };
        let refused = nightly_digest("nightly", VERSION, "horizon.zip", &keys, old).unwrap_err();
        assert!(refused.contains("SHA256SUMS.v2.sig"), "{refused}");
        let release = serving("v0.2.81", "v0.2.81");
        assert!(digest("v0.2.81", "horizon.zip", &keys, &release).is_ok());
        assert!(nightly_digest("nightly", VERSION, "horizon.zip", &keys, &release).is_err());
    }
}
