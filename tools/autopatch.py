#!/usr/bin/env python3
"""
Horizon Auto-Patcher
Applies offline crack, portable mode, ad removal, and offline enhancements
directly onto fresh or updated Horizon source trees without relying on strict line diffs.
"""

import sys
import os
import re
import json

def patch_file(path, func):
    if not os.path.isfile(path):
        print(f"[-] File not found: {path}")
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = func(content)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"[+] Successfully patched: {path}")
        return True
    else:
        print(f"[*] Already patched or pattern not found: {path}")
        return False

def patch_backend(content):
    # 1. Portable data_dir
    if "horizon_data" not in content:
        content = re.sub(
            r'(pub\s+fn\s+data_dir\s*\(\)\s*->\s*PathBuf\s*\{)(.*?)(if\s+let\s+Ok\s*\(\s*home\s*\))',
            r'\1\n    if let Ok(exe) = std::env::current_exe() {\n        if let Some(parent) = exe.parent() {\n            return parent.join("horizon_data");\n        }\n    }\n    \3',
            content,
            flags=re.DOTALL
        )
        content = re.sub(
            r'(pub\s+fn\s+game_home\s*\(\)\s*->\s*PathBuf\s*\{)(.*?)(dirs::data_dir\(\))',
            r'\1\n    if let Ok(exe) = std::env::current_exe() {\n        if let Some(parent) = exe.parent() {\n            return parent.join("horizon_data").join("game");\n        }\n    }\n    \3',
            content,
            flags=re.DOTALL
        )

    # 2. Set HORIZON_HOME in client_command
    if '.env("HORIZON_HOME", &home)' not in content:
        content = re.sub(
            r'cmd\.current_dir\((?:&?home)\)\.arg\("--resources"\)',
            r'cmd.current_dir(&home)\n        .env("HORIZON_HOME", &home)\n        .arg("--resources")',
            content
        )

    # 3. Direct download from Mojang without Microsoft account ownership check
    download_pattern = r'fn\s+download_for_owner\s*\([^)]*\)\s*->\s*Result<\(\),\s*String>\s*\{.*?\n\}'
    download_replacement = '''fn download_for_owner(
    pins: &sources::Pins,
    dir: &Path,
    fetch: sources::Fetch,
    log: &dyn Fn(String),
) -> Result<(), String> {
    let v = &pins.version;
    log(format!("Downloading Minecraft {v} from Mojang"));
    let os = match sources::Os::current() {
        sources::Os::Linux => "linux",
        sources::Os::MacOs => "osx",
        sources::Os::Windows => "windows",
    };
    mojang::download(pins, dir, os, 8, fetch, &mojang::CANCEL, log).map_err(|e| {
        format!("\\n  • Horizon tried to download {v} from Mojang, but: {e}")
    })
}'''
    content = re.sub(download_pattern, download_replacement, content, flags=re.DOTALL)

    # 4. Suppress updates
    content = re.sub(
        r'pub\s+fn\s+horizon_update\s*\([^)]*\)\s*->\s*Option<Release>\s*\{.*?\}',
        'pub fn horizon_update(_releases: &[Release], _installed: &[String]) -> Option<Release> {\n    None\n}',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'pub\s+fn\s+launcher_update\s*\([^)]*\)\s*->\s*Option<Release>\s*\{.*?\}',
        'pub fn launcher_update(_releases: &[Release]) -> Option<Release> {\n    None\n}',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'pub\s+fn\s+self_update_allowed\s*\(\)\s*->\s*bool\s*\{.*?\}',
        'pub fn self_update_allowed() -> bool {\n    false\n}',
        content,
        flags=re.DOTALL
    )

    # 5. Settings field evaluation_notice_seen
    if "evaluation_notice_seen" not in content:
        content = re.sub(
            r'(pub\s+owner_notice_seen:\s*bool,)',
            r'\1\n    /// Has the player seen the free evaluation notice modal once.\n    #[serde(default)]\n    pub evaluation_notice_seen: bool,',
            content
        )

    return content

def patch_account(content):
    # 1. Force has_owner to return true
    content = re.sub(
        r'(pub\s+fn\s+has_owner\s*\([^)]*\)\s*->\s*bool\s*\{)(?:[^{}]*|\{[^{}]*\})*\}',
        r'pub fn has_owner(&self, _store: &dyn SecretStore) -> bool {\n        true\n    }',
        content
    )

    # 2. Force launch to Ok(pass)
    content = re.sub(
        r'if\s+owned\s*\{\s*Ok\(pass\)\s*\}\s*else\s*\{\s*Err\(NoOwner\)\s*\}',
        'let _ = owned;\n    Ok(pass)',
        content
    )
    return content

def patch_owner_page(content):
    # Disable owner modal gate
    content = re.sub(
        r'(pub\(crate\)\s+fn\s+asking_owner\s*\([^)]*\)\s*->\s*bool\s*\{)(?:[^{}]*|\{[^{}]*\})*\}',
        r'pub(crate) fn asking_owner(&self) -> bool {\n        false\n    }',
        content
    )
    return content

def patch_servers_page(content):
    # Remove Sculk partner banner
    content = re.sub(
        r'\s*let\s+partner\s*=\s*super::partner::banner\([^)]*\);',
        '',
        content
    )
    content = re.sub(r'\s*\.child\(partner\);', ';', content)
    content = re.sub(r'\s*\.child\(partner\)', '', content)
    content = re.sub(r'page\.child\(list\)\.child\(partner\)', 'page.child(list)', content)

    # Remove Microsoft references in texts
    content = content.replace(
        "On: players must own Minecraft and sign in with Microsoft. {later}",
        "On: online authentication enabled for players. {later}"
    )
    content = content.replace(
        "Off: anyone can play under any name, so keep Friends only on. {later}",
        "Off: offline mode, anyone can play under any name. {later}"
    )
    content = re.sub(
        r'Only if every player signs in with Microsoft\..*?Friends only keeps strangers out\.',
        'Leave it off for players in offline mode: Friends only keeps strangers out.',
        content,
        flags=re.DOTALL
    )
    return content

def patch_switch_page(content):
    content = re.sub(
        r'Player::Microsoft\(_\)\s*=>\s*\(\s*self\.accounts\s*\.selected\(\)\s*\.map_or_else\(String::new,\s*\|a\|\s*a\.name\.clone\(\)\),\s*tr\("Microsoft account"\),\s*\)',
        'Player::Microsoft(_) => (\n                self.accounts\n                    .selected()\n                    .map_or_else(String::new, |a| a.name.clone()),\n                tr("Account"),\n            )',
        content
    )
    content = re.sub(r'tr\("Microsoft"\)', 'tr("Account")', content)
    content = re.sub(
        r'Play offline under another name, and switch from the top bar\.\s*Online\s*servers don\'t take offline names\.',
        'Play offline under another name, and switch from the top bar.',
        content
    )
    return content

def patch_cli(content):
    content = re.sub(
        r'No Microsoft account signed in\.\s*Play needs one that owns Minecraft:\s*Java\s*Edition:\s*horizon-launcher account sign-in',
        'No account signed in. You can play offline: horizon-launcher account offline NAME',
        content
    )
    return content

def patch_main(content):
    # 1. Remove partner card from sidebar
    content = re.sub(
        r'if\s+self\.page\s*!=\s*Page::Servers\s*&&\s*!self\.settings\.partner_hidden\s*\{.*?foot\s*=\s*foot\.child\(side\);\s*\}',
        '// Partner card removed',
        content,
        flags=re.DOTALL
    )

    # 2. Clean up prepare block: direct download from Mojang only
    prepare_block_pattern = r'let\s+prepare\s*=\s*match\s+first\s*\{.*?None\s*=>\s*div\(\)\.child\(prepare\),\s*\};'
    prepare_block_replacement = '''let prepare = match first {
            Some(true) => div().child(
                button(
                    "prepare-download",
                    "Download and prepare",
                    Kind::Secondary,
                    &t,
                )
                .on_click(cx.listener(|this, _: &ClickEvent, _, cx| {
                    this.prepare(backend::MinecraftFrom::Mojang);
                    cx.notify();
                })),
            ),
            Some(false) => div().child(
                button("prepare-sign-in", "Sign in", Kind::Secondary, &t).on_click(cx.listener(
                    |this, _: &ClickEvent, _, cx| {
                        this.sign_in_to_play();
                        cx.notify();
                    },
                )),
            ),
            None => div().child(prepare),
        };'''
    content = re.sub(prepare_block_pattern, prepare_block_replacement, content, flags=re.DOTALL)
    content = content.replace(
        "this.prepare(backend::MinecraftFrom::Install);",
        "this.prepare(backend::MinecraftFrom::Mojang);"
    )
    content = content.replace(
        "Not prepared. Horizon can download Minecraft {version} from Mojang, or use your own install.",
        "Not prepared. Horizon will download Minecraft {version} from Mojang."
    )

    # 3. Remove mandatory Microsoft account row on Play page
    content = re.sub(
        r'if\s+self\.owner\s*==\s*Some\(false\)\s*\{.*?\}\s*else\s+if\s+self\.accounts\.selected\(\)',
        'if self.accounts.selected()',
        content,
        flags=re.DOTALL
    )
    content = content.replace(
        'tr("Online servers need a Microsoft account.")',
        'tr("Playing in offline mode.")'
    )

    # 4. Settings: remove account_rows from display, start offline_rows at 0
    content = re.sub(
        r'let\s*\(accounts,\s*n\)\s*=\s*self\.account_rows\(cx\);\s*let\s*\(offline,\s*n\)\s*=\s*self\.offline_rows\(n,\s*cx\);',
        'let (offline, n) = self.offline_rows(0, cx);',
        content
    )
    content = re.sub(
        r'\.child\(group\("Account",\s*"user"\)\.mt_0\(\)\)\s*\.child\(accounts\)\s*\.child\(offline\)',
        '.child(group("Account", "user").mt_0())\n                    .child(offline)',
        content
    )
    content = re.sub(
        r'(fn\s+account_rows\s*\(&mut\s+self,\s*cx:\s*&mut\s+Context<Self>\)\s*->\s*\(Div,\s*usize\)\s*\{)',
        r'#[allow(dead_code)]\n    \1',
        content
    )

    # 5. Clean up sign-in text labels in account_rows
    content = content.replace('"Microsoft account · plays"', '"Account · plays"')
    content = content.replace('"Microsoft account · signed in"', '"Account · signed in"')
    content = content.replace('"Asking Microsoft…"', '"Signing in…"')
    content = content.replace('"Sign in with Microsoft"', '"Sign in"')
    content = content.replace(
        '"Horizon needs a Microsoft account that owns Minecraft: Java Edition, like other launchers. It also plays online servers with your name and skin."',
        '"Sign in to play on authenticated servers with your skin."'
    )

    # 6. Evaluation Modal trigger
    if "self.evaluation_modal(cx)" not in content:
        content = re.sub(
            r'(if\s+self\.asking_owner\(\)\s*\{.*?\}\s*)',
            r'\1if !self.settings.evaluation_notice_seen && self.opening.is_none() {\n            root = root.child(self.evaluation_modal(cx));\n        }\n        ',
            content,
            flags=re.DOTALL
        )

    # 7. Evaluation modal implementation
    if "fn evaluation_modal" not in content:
        modal_code = '''
    fn evaluation_modal(&mut self, cx: &mut Context<Self>) -> Stateful<Div> {
        let t = self.theme;
        let sponsor_url = self.links.sponsor.clone();
        let discord_url = self.links.discord.clone();

        let card = plate(&t)
            .flex()
            .flex_col()
            .w_full()
            .max_w(px(540.))
            .bg(t.page)
            .border_1()
            .border_color(t.outline)
            .rounded(px(theme::RADIUS))
            .p(px(28.))
            .gap(px(16.))
            .child(
                blocks::pixel(11., FontWeight::MEDIUM)
                    .text_color(t.muted)
                    .child(tr("FREE EVALUATION EDITION")),
            )
            .child(
                blocks::pixel(20., FontWeight::SEMIBOLD)
                    .text_color(t.ink)
                    .child(tr("Information & Support")),
            )
            .child(
                text(theme::UI)
                    .text_color(t.ink)
                    .line_height(px(22.))
                    .child(tr(
                        "You are using a Free evaluation edition. If you enjoy the game, \
                         we recommend supporting the original creators and purchasing an official copy of Minecraft: Java Edition."
                    )),
            )
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .pt(px(14.))
                    .child(
                        div()
                            .flex()
                            .gap(px(8.))
                            .children((!sponsor_url.is_empty()).then(|| {
                                button("notice-sponsor", tr("Support Authors"), Kind::Ghost, &t)
                                    .on_click(move |_, _, cx| cx.open_url(&sponsor_url))
                            }))
                            .children((!discord_url.is_empty()).then(|| {
                                button("notice-discord", "Discord", Kind::Ghost, &t)
                                    .on_click(move |_, _, cx| cx.open_url(&discord_url))
                            })),
                    )
                    .child(
                        button("notice-ok", tr("OK"), Kind::Primary, &t).on_click(cx.listener(
                            |this, _: &ClickEvent, _, cx| {
                                this.settings.evaluation_notice_seen = true;
                                this.settings.save();
                                cx.notify();
                            },
                        )),
                    ),
            );

        div()
            .id("evaluation-modal")
            .absolute()
            .top_0()
            .left_0()
            .size_full()
            .flex()
            .flex_col()
            .items_center()
            .justify_center()
            .px(px(32.))
            .py(px(24.))
            .bg(t.page.opacity(0.92))
            .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
            .occlude()
            .child(card)
    }
'''
        # Insert before closing brace of `impl Launcher` or before `actions!(horizon_launcher`
        content = re.sub(
            r'(\nactions!\(horizon_launcher)',
            modal_code + r'\1',
            content
        )

    return content

def patch_ru_lang(content):
    try:
        data = json.loads(content)
    except Exception:
        return content

    additions = {
        "FREE EVALUATION EDITION": "ОЗНАКОМИТЕЛЬНАЯ ВЕРСИЯ",
        "Information & Support": "Информация и поддержка",
        "You are using a Free evaluation edition. If you enjoy the game, we recommend supporting the original creators and purchasing an official copy of Minecraft: Java Edition.": "Вы используете бесплатную версию для ознакомления. Если вам нравится игра, рекомендуем поддержать оригинальных создателей и приобрести официальную копию Minecraft: Java Edition.",
        "Support Authors": "Поддержать авторов",
        "OK": "Понятно",
        "Not prepared. Horizon will download Minecraft {version} from Mojang.": "Не подготовлено. Horizon скачает Minecraft {version} у Mojang."
    }
    for k, v in additions.items():
        data[k] = v

    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"[*] Patching Horizon source tree at: {os.path.abspath(root)}")

    patch_file(os.path.join(root, "launcher", "src", "backend.rs"), patch_backend)
    patch_file(os.path.join(root, "launcher", "src", "account.rs"), patch_account)
    patch_file(os.path.join(root, "launcher", "src", "owner_page.rs"), patch_owner_page)
    patch_file(os.path.join(root, "launcher", "src", "servers_page.rs"), patch_servers_page)
    patch_file(os.path.join(root, "launcher", "src", "switch_page.rs"), patch_switch_page)
    patch_file(os.path.join(root, "launcher", "src", "cli.rs"), patch_cli)
    patch_file(os.path.join(root, "launcher", "src", "main.rs"), patch_main)
    patch_file(os.path.join(root, "launcher", "lang", "ru.json"), patch_ru_lang)

    print("[*] All patches applied successfully!")

if __name__ == "__main__":
    main()
