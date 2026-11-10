//! Who plays: the top bar's quick switch (a menu under the account chip) between the signed-in
//! Microsoft accounts.
use super::*;

impl Launcher {
    /// The chip's two lines: the name that plays, and how.
    pub(super) fn who_plays(&self) -> (String, &'static str) {
        match self.accounts.selected() {
            Some(a) => (a.name.clone(), tr("Offline mode")),
            None => (tr("Player").to_string(), tr("Offline mode")),
        }
    }

    pub(super) fn play_as(&mut self, uuid: &str) {
        let mut accounts = Accounts::load();
        let done = accounts.play_as(uuid).and_then(|()| accounts.save());
        match done {
            Ok(()) => self.accounts = accounts,
            Err(e) => self.sign_in_state = Some(SignInState::Done(Err(e))),
        }
        self.account_menu = false;
    }

    pub(super) fn remove_account(&mut self, uuid: &str) {
        let mut accounts = Accounts::load();
        accounts.accounts.retain(|a| a.uuid != uuid);
        if accounts.selected.as_deref() == Some(uuid) {
            accounts.selected = accounts.accounts.first().map(|a| a.uuid.clone());
        }
        let _ = accounts.save();
        self.accounts = accounts;
        self.load_profile_heads();
    }

    /// Everyone the player can play as (each account's UUID and name), with how each signs in.
    pub(super) fn players(&self) -> Vec<(String, String, &'static str)> {
        if self.accounts.accounts.is_empty() {
            let default_uuid = format!(
                "{:032x}",
                horizon_platform::protocol::offline_uuid("Player")
            );
            vec![(default_uuid, tr("Player").to_string(), tr("Offline"))]
        } else {
            self.accounts
                .accounts
                .iter()
                .map(|a| (a.uuid.clone(), a.name.clone(), tr("Offline")))
                .collect()
        }
    }

    /// The menu under the account chip, while open.
    pub(super) fn account_menu(&self, cx: &mut Context<Self>) -> Option<impl IntoElement> {
        if !self.account_menu {
            return None;
        }
        let t = self.theme;
        let now = self.accounts.selected().map(|a| a.uuid.clone());
        let mut menu = div()
            .id("account-menu")
            .absolute()
            .top(px(46.))
            .right_0()
            .w(px(280.))
            .p(px(6.))
            .border_2()
            .border_color(t.outline)
            .bg(t.surface)
            .flex()
            .flex_col()
            .occlude()
            .on_mouse_down_out(cx.listener(|this, event: &MouseDownEvent, _, cx| {
                this.account_menu = false;
                this.menu_closed_at = Some(event.position);
                cx.notify();
            }));
        let can_remove = self.accounts.accounts.len() > 1;
        for (i, (who, name, how)) in self.players().into_iter().enumerate() {
            let chosen = Some(&who) == now.as_ref();
            let who_pick = who.clone();
            let who_del = who.clone();
            menu = menu.child(
                div()
                    .id(SharedString::from(format!("account-pick-{i}")))
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(8.))
                    .h(px(46.))
                    .px(px(10.))
                    .rounded(px(theme::RADIUS))
                    .hover(move |s| s.bg(t.plate_soft))
                    .child(
                        div()
                            .id(SharedString::from(format!("account-select-{i}")))
                            .flex()
                            .items_center()
                            .gap(px(8.))
                            .flex_1()
                            .min_w_0()
                            .cursor_pointer()
                            .child(self.profile_heads.draw(
                                Some(who_pick.as_str()),
                                24.,
                                self.scale,
                                &t,
                            ))
                            .child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .flex_1()
                                    .min_w_0()
                                    .child(
                                        text(theme::LABEL).truncate().text_color(t.ink).child(name),
                                    )
                                    .child(text(theme::CAPTION).text_color(t.muted).child(how)),
                            )
                            .on_click(cx.listener(move |this, _: &ClickEvent, _, cx| {
                                this.play_as(&who_pick);
                                cx.notify();
                            })),
                    )
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(6.))
                            .when(chosen, |d| {
                                d.child(div().size(px(6.)).rounded_full().bg(t.accent))
                            })
                            .when(can_remove, |d| {
                                d.child(
                                    div()
                                        .id(SharedString::from(format!("account-del-{i}")))
                                        .size(px(24.))
                                        .flex()
                                        .items_center()
                                        .justify_center()
                                        .rounded(px(4.))
                                        .cursor_pointer()
                                        .hover(move |s| s.bg(t.danger.opacity(0.18)))
                                        .child(blocks::icon("close", 14., t.muted))
                                        .on_click(cx.listener(
                                            move |this, _: &ClickEvent, _, cx| {
                                                this.remove_account(&who_del);
                                                cx.notify();
                                            },
                                        )),
                                )
                            }),
                    ),
            );
        }
        menu = menu.child(div().my(px(6.)).h(px(1.)).bg(t.rule)).child(
            div()
                .id("account-manage")
                .flex()
                .items_center()
                .h(px(32.))
                .px(px(10.))
                .rounded(px(theme::RADIUS))
                .text_size(px(theme::LABEL.px))
                .text_color(t.muted)
                .cursor_pointer()
                .hover(move |s| s.bg(t.plate_soft).text_color(t.ink))
                .child(tr("Manage accounts"))
                .on_click(cx.listener(|this, _: &ClickEvent, _, cx| {
                    this.account_menu = false;
                    this.go(Page::Settings);
                    cx.notify();
                })),
        );
        Some(gpui::deferred(menu).with_priority(1))
    }
}
