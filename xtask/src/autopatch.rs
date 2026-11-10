use regex::Regex;
use std::fs;
use std::path::Path;

fn patch_file<F>(path: &Path, f: F) -> Result<bool, String>
where
    F: FnOnce(&str) -> Result<String, String>,
{
    if !path.is_file() {
        return Err(format!("File not found: {}", path.display()));
    }
    let content = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let new_content = f(&content)?;
    if new_content != content {
        fs::write(path, new_content).map_err(|e| e.to_string())?;
        println!("[+] Successfully patched: {}", path.display());
        Ok(true)
    } else {
        println!("[*] Already patched: {}", path.display());
        Ok(false)
    }
}

pub fn autopatch(root: &Path) -> Result<(), String> {
    println!(
        "[*] Autopatching Horizon source tree at: {}",
        root.display()
    );

    let backend_path = root.join("launcher").join("src").join("backend.rs");
    patch_file(&backend_path, |content| {
        let mut s = content.to_string();
        if !s.contains("horizon_data") {
            let re_data = Regex::new(r"(pub\s+fn\s+data_dir\s*\(\)\s*->\s*PathBuf\s*\{)([\s\S]*?)(if\s+let\s+Some\(home\))").unwrap();
            s = re_data.replace(&s, "$1\n    if let Ok(exe) = std::env::current_exe() {\n        if let Some(parent) = exe.parent() {\n            return parent.join(\"horizon_data\");\n        }\n    }\n    $3").into_owned();

            let re_home = Regex::new(
                r"(pub\s+fn\s+game_home\s*\(\)\s*->\s*PathBuf\s*\{)([\s\S]*?)(dirs::data_dir\(\))",
            )
            .unwrap();
            s = re_home.replace(&s, "$1\n    if let Ok(exe) = std::env::current_exe() {\n        if let Some(parent) = exe.parent() {\n            return parent.join(\"horizon_data\").join(\"game\");\n        }\n    }\n    $3").into_owned();
        }

        if !s.contains(r#".env("HORIZON_HOME", &home)"#) {
            s = s.replace(
                "cmd.current_dir(home).arg(\"--resources\")",
                "cmd.current_dir(&home)\n        .env(\"HORIZON_HOME\", &home)\n        .arg(\"--resources\")",
            );
            s = s.replace(
                "cmd.current_dir(&home).arg(\"--resources\")",
                "cmd.current_dir(&home)\n        .env(\"HORIZON_HOME\", &home)\n        .arg(\"--resources\")",
            );
        }

        let re_download = Regex::new(
            r"fn\s+download_for_owner\s*\([^)]*\)\s*->\s*Result<\(\),\s*String>\s*\{[\s\S]*?\n\}",
        )
        .unwrap();
        let download_repl = "fn download_for_owner(\n    pins: &sources::Pins,\n    dir: &Path,\n    fetch: sources::Fetch,\n    log: &dyn Fn(String),\n) -> Result<(), String> {\n    let v = &pins.version;\n    log(format!(\"Downloading Minecraft {v} from Mojang\"));\n    let os = match sources::Os::current() {\n        sources::Os::Linux => \"linux\",\n        sources::Os::MacOs => \"osx\",\n        sources::Os::Windows => \"windows\",\n    };\n    mojang::download(pins, dir, os, 8, fetch, &mojang::CANCEL, log).map_err(|e| {\n        format!(\"\\n  • Horizon tried to download {v} from Mojang, but: {e}\")\n    })\n}";
        s = re_download.replace(&s, download_repl).into_owned();

        let re_hz_up = Regex::new(
            r"pub\s+fn\s+horizon_update\s*\([^)]*\)\s*->\s*Option<Release>\s*\{[\s\S]*?\}",
        )
        .unwrap();
        s = re_hz_up.replace(&s, "pub fn horizon_update(_releases: &[Release], _installed: &[String]) -> Option<Release> {\n    None\n}").into_owned();

        let re_ln_up = Regex::new(
            r"pub\s+fn\s+launcher_update\s*\([^)]*\)\s*->\s*Option<Release>\s*\{[\s\S]*?\}",
        )
        .unwrap();
        s = re_ln_up
            .replace(
                &s,
                "pub fn launcher_update(_releases: &[Release]) -> Option<Release> {\n    None\n}",
            )
            .into_owned();

        let re_self_up =
            Regex::new(r"pub\s+fn\s+self_update_allowed\s*\(\)\s*->\s*bool\s*\{[\s\S]*?\}")
                .unwrap();
        s = re_self_up
            .replace(&s, "pub fn self_update_allowed() -> bool {\n    false\n}")
            .into_owned();

        if !s.contains("evaluation_notice_seen") {
            s = s.replace(
                "pub owner_notice_seen: bool,",
                "pub owner_notice_seen: bool,\n    /// Has the player seen the free evaluation notice modal once.\n    #[serde(default)]\n    pub evaluation_notice_seen: bool,",
            );
        }
        Ok(s)
    })?;

    let account_path = root.join("launcher").join("src").join("account.rs");
    patch_file(&account_path, |content| {
        let mut s = content.to_string();
        let re_owner = Regex::new(
            r"(pub\s+fn\s+has_owner\s*\([^)]*\)\s*->\s*bool\s*\{)(?:[^{}]*|\{[^{}]*\})*\}",
        )
        .unwrap();
        s = re_owner
            .replace(
                &s,
                "pub fn has_owner(&self, _store: &dyn SecretStore) -> bool {\n        true\n    }",
            )
            .into_owned();

        let re_launch =
            Regex::new(r"if\s+owned\s*\{\s*Ok\(pass\)\s*\}\s*else\s*\{\s*Err\(NoOwner\)\s*\}")
                .unwrap();
        s = re_launch
            .replace(&s, "let _ = owned;\n    Ok(pass)")
            .into_owned();
        Ok(s)
    })?;

    let owner_page_path = root.join("launcher").join("src").join("owner_page.rs");
    patch_file(&owner_page_path, |content| {
        let re_asking = Regex::new(r"(pub\(crate\)\s+fn\s+asking_owner\s*\([^)]*\)\s*->\s*bool\s*\{)(?:[^{}]*|\{[^{}]*\})*\}").unwrap();
        Ok(re_asking
            .replace(
                content,
                "pub(crate) fn asking_owner(&self) -> bool {\n        false\n    }",
            )
            .into_owned())
    })?;

    let servers_path = root.join("launcher").join("src").join("servers_page.rs");
    patch_file(&servers_path, |content| {
        let mut s = content.to_string();
        let re_partner =
            Regex::new(r"\s*let\s+partner\s*=\s*super::partner::banner\([^)]*\);").unwrap();
        s = re_partner.replace_all(&s, "").into_owned();
        s = s.replace(".child(partner);", ";");
        s = s.replace(".child(partner)", "");
        s = s.replace("page.child(list).child(partner)", "page.child(list)");
        s = s.replace(
            "On: players must own Minecraft and sign in with Microsoft. {later}",
            "On: online authentication enabled for players. {later}",
        );
        s = s.replace(
            "Off: anyone can play under any name, so keep Friends only on. {later}",
            "Off: offline mode, anyone can play under any name. {later}",
        );

        let re_strangers = Regex::new(
            r"Only if every player signs in with Microsoft\..*?Friends only keeps strangers out\.",
        )
        .unwrap();
        s = re_strangers
            .replace(
                &s,
                "Leave it off for players in offline mode: Friends only keeps strangers out.",
            )
            .into_owned();
        Ok(s)
    })?;

    let switch_path = root.join("launcher").join("src").join("switch_page.rs");
    patch_file(&switch_path, |content| {
        let mut s = content.to_string();
        let re_sw = Regex::new(r#"Player::Microsoft\(_\)\s*=>\s*\(\s*self\.accounts\s*\.selected\(\)\s*\.map_or_else\(String::new,\s*\|a\|\s*a\.name\.clone\(\)\),\s*tr\("Microsoft account"\),\s*\)"#).unwrap();
        s = re_sw.replace(&s, "Player::Microsoft(_) => (\n                self.accounts\n                    .selected()\n                    .map_or_else(String::new, |a| a.name.clone()),\n                tr(\"Account\"),\n            )").into_owned();
        s = s.replace("tr(\"Microsoft\")", "tr(\"Account\")");
        let re_offline_desc = Regex::new(r"Play offline under another name, and switch from the top bar\.\s*Online\s*servers don't take offline names\.").unwrap();
        s = re_offline_desc
            .replace(
                &s,
                "Play offline under another name, and switch from the top bar.",
            )
            .into_owned();
        Ok(s)
    })?;

    let cli_path = root.join("launcher").join("src").join("cli.rs");
    patch_file(&cli_path, |content| {
        let re_cli = Regex::new(r"No Microsoft account signed in\.\s*Play needs one that owns Minecraft:\s*Java\s*Edition:\s*horizon-launcher account sign-in").unwrap();
        Ok(re_cli
            .replace(
                content,
                "No account signed in. You can play offline: horizon-launcher account offline NAME",
            )
            .into_owned())
    })?;

    let main_path = root.join("launcher").join("src").join("main.rs");
    patch_file(&main_path, |content| {
        let mut s = content.to_string();
        let re_partner_side = Regex::new(r"if\s+self\.page\s*!=\s*Page::Servers\s*&&\s*!self\.settings\.partner_hidden\s*\{[\s\S]*?foot\s*=\s*foot\.child\(side\);\s*\}").unwrap();
        s = re_partner_side
            .replace(&s, "// Partner card removed")
            .into_owned();

        let re_prep_block = Regex::new(r"let\s+prepare\s*=\s*match\s+first\s*\{[\s\S]*?None\s*=>\s*div\(\)\.child\(prepare\),\s*\};").unwrap();
        let prep_repl = "let prepare = match first {\n            Some(true) => div().child(\n                button(\n                    \"prepare-download\",\n                    \"Download and prepare\",\n                    Kind::Secondary,\n                    &t,\n                )\n                .on_click(cx.listener(|this, _: &ClickEvent, _, cx| {\n                    this.prepare(backend::MinecraftFrom::Mojang);\n                    cx.notify();\n                })),\n            ),\n            Some(false) => div().child(\n                button(\"prepare-sign-in\", \"Sign in\", Kind::Secondary, &t).on_click(cx.listener(\n                    |this, _: &ClickEvent, _, cx| {\n                        this.sign_in_to_play();\n                        cx.notify();\n                    },\n                )),\n            ),\n            None => div().child(prepare),\n        };";
        s = re_prep_block.replace(&s, prep_repl).into_owned();
        s = s.replace(
            "this.prepare(backend::MinecraftFrom::Install);",
            "this.prepare(backend::MinecraftFrom::Mojang);",
        );
        s = s.replace("Not prepared. Horizon can download Minecraft {version} from Mojang, or use your own install.", "Not prepared. Horizon will download Minecraft {version} from Mojang.");

        let re_owner_row = Regex::new(r"if\s+self\.owner\s*==\s*Some\(false\)\s*\{[\s\S]*?\}\s*else\s+if\s+self\.accounts\.selected\(\)").unwrap();
        s = re_owner_row
            .replace(&s, "if self.accounts.selected()")
            .into_owned();
        s = s.replace(
            "tr(\"Online servers need a Microsoft account.\")",
            "tr(\"Playing in offline mode.\")",
        );

        let re_acc_rows = Regex::new(r"let\s*\(accounts,\s*n\)\s*=\s*self\.account_rows\(cx\);\s*let\s*\(offline,\s*n\)\s*=\s*self\.offline_rows\(n,\s*cx\);").unwrap();
        s = re_acc_rows
            .replace(&s, "let (offline, n) = self.offline_rows(0, cx);")
            .into_owned();

        let re_acc_group = Regex::new(r#"\.child\(group\("Account",\s*"user"\)\.mt_0\(\)\)\s*\.child\(accounts\)\s*\.child\(offline\)"#).unwrap();
        s = re_acc_group
            .replace(
                &s,
                ".child(group(\"Account\", \"user\").mt_0())\n                    .child(offline)",
            )
            .into_owned();

        let re_acc_fn = Regex::new(r"(fn\s+account_rows\s*\(&mut\s+self,\s*cx:\s*&mut\s+Context<Self>\)\s*->\s*\(Div,\s*usize\)\s*\{)").unwrap();
        s = re_acc_fn
            .replace(&s, "#[allow(dead_code)]\n    $1")
            .into_owned();

        s = s.replace("\"Microsoft account · plays\"", "\"Account · plays\"");
        s = s.replace(
            "\"Microsoft account · signed in\"",
            "\"Account · signed in\"",
        );
        s = s.replace("\"Asking Microsoft…\"", "\"Signing in…\"");
        s = s.replace("\"Sign in with Microsoft\"", "\"Sign in\"");
        s = s.replace(
            "\"Horizon needs a Microsoft account that owns Minecraft: Java Edition, like other launchers. It also plays online servers with your name and skin.\"",
            "\"Sign in to play on authenticated servers with your skin.\"",
        );

        if !s.contains("self.evaluation_modal(cx)") {
            let re_eval_trig =
                Regex::new(r"(if\s+self\.asking_owner\(\)\s*\{[\s\S]*?\}\s*)").unwrap();
            s = re_eval_trig.replace(&s, "$1if !self.settings.evaluation_notice_seen && self.opening.is_none() {\n            root = root.child(self.evaluation_modal(cx));\n        }\n        ").into_owned();
        }

        if !s.contains("fn evaluation_modal") {
            let modal_body = r#"
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
"#;
            s = s.replace(
                "actions!(horizon_launcher",
                &format!("{modal_body}\nactions!(horizon_launcher"),
            );
        }
        Ok(s)
    })?;

    let ru_path = root.join("launcher").join("lang").join("ru.json");
    patch_file(&ru_path, |content| {
        let mut s = content.to_string();
        if !s.contains("FREE EVALUATION EDITION") {
            let addition = ",\n  \"FREE EVALUATION EDITION\": \"ОЗНАКОМИТЕЛЬНАЯ ВЕРСИЯ\",\n  \"Information & Support\": \"Информация и поддержка\",\n  \"You are using a Free evaluation edition. If you enjoy the game, we recommend supporting the original creators and purchasing an official copy of Minecraft: Java Edition.\": \"Вы используете бесплатную версию для ознакомления. Если вам нравится игра, рекомендуем поддержать оригинальных создателей и приобрести официальную копию Minecraft: Java Edition.\",\n  \"Support Authors\": \"Поддержать авторов\",\n  \"OK\": \"Понятно\",\n  \"Not prepared. Horizon will download Minecraft {version} from Mojang.\": \"Не подготовлено. Horizon скачает Minecraft {version} у Mojang.\"\n}";
            let re_end = Regex::new(r"\n\}").unwrap();
            s = re_end.replace(&s, addition).into_owned();
        }
        Ok(s)
    })?;

    println!("[*] Autopatch complete!");
    Ok(())
}
