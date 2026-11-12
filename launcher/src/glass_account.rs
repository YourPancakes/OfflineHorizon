//! Settings' Account card in the glass look, as the mockup's: who plays now (a big head, the
//! name, how), and the Microsoft card beside it with its white Sign in with Microsoft button.
//!
//! Not in the mockup, kept in its patterns: the Microsoft accounts already signed in (in the
//! Microsoft card, with Play as, Refresh and Sign out), the sign-in's code, progress and problems.

use super::*;
use crate::glass_ui::{self as ui, white, Tone};
use horizon_theme::glass::{ink, radius};

impl Launcher {
    pub(super) fn glass_account(&mut self, cx: &mut Context<Self>) -> Div {
        let wide = self.window_width >= crate::glass_home::WIDE;
        let left = self.glass_who_plays();
        let right = self.glass_microsoft_card(cx);
        if wide {
            div()
                .flex()
                .flex_row()
                .gap(px(8.))
                .child(left.flex_1().min_w(px(280.)).p(px(20.)))
                .child(right.flex_none().w(px(360.)))
        } else {
            div()
                .flex()
                .flex_col()
                .gap(px(16.))
                .child(left.w_full().min_w_0().p(px(20.)))
                .child(right.w_full())
        }
    }

    /// The player now.
    fn glass_who_plays(&self) -> Div {
        let t = self.theme;
        let (uuid, name, status) = match self.accounts.selected() {
            Some(a) => (
                Some(a.uuid.clone()),
                a.name.clone(),
                (Tone::Live, tr("Player · Offline mode")),
            ),
            None => (
                None,
                tr("Player").to_string(),
                (Tone::Off, tr("Ready to play")),
            ),
        };
        let head = div()
            .flex_none()
            .size(px(80.))
            .rounded(px(20.))
            .overflow_hidden()
            .child(
                self.profile_heads
                    .draw(uuid.as_deref(), 80., self.scale, &t),
            );
        let header = div().flex().items_center().gap(px(20.)).child(head).child(
            div()
                .flex()
                .flex_col()
                .min_w_0()
                .gap(px(10.))
                .child(
                    div()
                        .font_family(horizon_theme::glass::DISPLAY_FONT)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(32.))
                        .line_height(px(32.))
                        .text_color(white(ink::FULL))
                        .truncate()
                        .child(name),
                )
                .child(
                    div()
                        .flex()
                        .items_start()
                        .gap(px(8.))
                        .child(ui::dot(status.0).mt(px(7.)))
                        .child(
                            ui::text(14., FontWeight::NORMAL, 0.65)
                                .flex_1()
                                .min_w_0()
                                .line_height(px(21.))
                                .child(status.1),
                        ),
                ),
        );

        div().flex().flex_col().child(header)
    }

    /// The player card with name editing.
    fn glass_microsoft_card(&mut self, cx: &mut Context<Self>) -> Div {
        let t = self.theme;
        let focused = self.player_name_focused;
        let placeholder = "Enter player name";
        let input_field = div()
            .id("offline-player-name-field")
            .track_focus(&self.player_name_focus)
            .flex()
            .items_center()
            .h(px(40.))
            .w_full()
            .px(px(14.))
            .rounded(px(radius::CONTROL))
            .border_2()
            .border_color(if focused {
                ui::color(self.look.accent_soft)
            } else {
                white(0.12)
            })
            .bg(white(0.06))
            .font_family(horizon_theme::glass::FONT)
            .text_size(px(14.))
            .cursor_text()
            .child(line_edit::content(
                &self.player_name_input,
                &t,
                focused,
                false,
                false,
                placeholder,
            ))
            .on_click(cx.listener(|this, _: &ClickEvent, window, cx| {
                window.focus(&this.player_name_focus, cx);
                this.player_name_focused = true;
                cx.notify();
            }))
            .on_key_down(cx.listener(|this, ev: &KeyDownEvent, window, cx| {
                match line_edit::handle(&mut this.player_name_input, ev, cx) {
                    line_edit::Key::Pass => return,
                    line_edit::Key::Enter => {
                        let name = this.player_name_input.text().trim().to_string();
                        if !name.is_empty() {
                            this.accounts.set_offline_name(&name);
                            let _ = this.accounts.save();
                            this.load_profile_heads();
                        }
                        window.blur(cx);
                        this.player_name_focused = false;
                    }
                    line_edit::Key::Escape => {
                        window.blur(cx);
                        this.player_name_focused = false;
                    }
                    line_edit::Key::Edited => {}
                    _ => {}
                }
                cx.stop_propagation();
                cx.notify();
            }));

        let save_btn = ui::solid("save-player-name", tr("Save Name"), 38., 14., &t).on_click(
            cx.listener(|this, _: &ClickEvent, window, cx| {
                let name = this.player_name_input.text().trim().to_string();
                if !name.is_empty() {
                    this.accounts.set_offline_name(&name);
                    let _ = this.accounts.save();
                    this.load_profile_heads();
                }
                window.blur(cx);
                this.player_name_focused = false;
                cx.notify();
            }),
        );

        div()
            .flex()
            .flex_col()
            .rounded(px(16.))
            .bg(white(0.045))
            .p(px(24.))
            .child(
                div()
                    .font_family(horizon_theme::glass::DISPLAY_FONT)
                    .font_weight(FontWeight::SEMIBOLD)
                    .text_size(px(22.))
                    .line_height(px(27.5))
                    .text_color(white(ink::FULL))
                    .child(tr("Player Profile")),
            )
            .child(
                ui::text(14., FontWeight::NORMAL, 0.65)
                    .mt(px(8.))
                    .line_height(px(21.7))
                    .child(tr(
                        "Set your offline nickname below. This name is used in game worlds and on local servers.",
                    )),
            )
            .child(
                div()
                    .mt(px(18.))
                    .flex()
                    .flex_col()
                    .gap(px(12.))
                    .child(line_edit::mouse(input_field, cx, |this| &mut this.player_name_input))
                    .child(div().flex().child(save_btn)),
            )
    }
}
