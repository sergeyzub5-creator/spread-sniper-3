from ui.styles import theme_color


class SpreadThemeMixin:
    def apply_theme(self):
        c_surface = theme_color("surface")
        c_window = theme_color("window_bg")
        c_border = theme_color("border")
        c_primary = theme_color("text_primary")
        c_muted = theme_color("text_muted")
        c_alt = theme_color("surface_alt")
        c_accent = theme_color("accent")
        c_success = theme_color("success")
        c_danger = theme_color("danger")
        c_capsule_border = self._rgba(c_accent, 0.52)
        c_capsule_glow = self._rgba(c_accent, 0.18)
        c_capsule_mid = self._rgba(c_alt, 0.95)
        c_capsule_hover = self._rgba(c_accent, 0.24)
        c_cheap_border = self._rgba(c_success, 0.76)
        c_cheap_tone = self._rgba(c_success, 0.20)
        c_cheap_hover = self._rgba(c_success, 0.30)
        c_exp_border = self._rgba(c_danger, 0.76)
        c_exp_tone = self._rgba(c_danger, 0.20)
        c_exp_hover = self._rgba(c_danger, 0.30)

        self.container.setStyleSheet(
            f"""
            QFrame#spreadContainer {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self._rgba(c_alt, 0.96)},
                    stop: 1 {self._rgba(c_window, 0.98)}
                );
                border: 1px solid {self._rgba(c_border, 0.58)};
                border-radius: 12px;
            }}
            QPushButton#exchangeSelector {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_capsule_glow},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
                color: {c_primary};
                border: 1px solid {c_capsule_border};
                border-radius: 22px;
                min-height: 40px;
                font-size: 12px;
                font-weight: 700;
                padding: 6px 10px;
            }}
            QPushButton#exchangeSelector:hover {{
                border-color: {c_accent};
                background-color: {c_capsule_hover};
            }}
            QPushButton#exchangeSelector[toneRole="cheap"] {{
                border-color: {c_cheap_border};
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_cheap_tone},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
            }}
            QPushButton#exchangeSelector[toneRole="cheap"]:hover {{
                border-color: {c_success};
                background-color: {c_cheap_hover};
            }}
            QPushButton#exchangeSelector[toneRole="expensive"] {{
                border-color: {c_exp_border};
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {c_exp_tone},
                    stop: 0.50 {c_capsule_mid},
                    stop: 1 {c_surface}
                );
            }}
            QPushButton#exchangeSelector[toneRole="expensive"]:hover {{
                border-color: {c_danger};
                background-color: {c_exp_hover};
            }}
            QPushButton#exchangeSelector:disabled {{
                color: {c_muted};
                border-color: {c_border};
                background-color: {c_alt};
            }}
            QLineEdit#pairSelector {{
                background-color: {c_alt};
                color: {c_primary};
                border: 1px solid {c_capsule_border};
                border-radius: 14px;
                min-height: 30px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 600;
            }}
            QLineEdit#pairSelector:hover {{
                border-color: {c_accent};
                background-color: {c_capsule_hover};
            }}
            QLineEdit#pairSelector:focus {{
                border-color: {c_accent};
            }}
            QLineEdit#pairSelector:disabled {{
                color: {c_muted};
                border-color: {c_border};
                background-color: {c_surface};
            }}
            QWidget#quotePanel {{
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }}
            QFrame#quoteSideCapsule {{
                background-color: {c_surface};
                border: none;
                border-radius: 8px;
            }}
            QFrame#quoteMidDivider {{
                background-color: {self._rgba(c_border, 0.55)};
                border: none;
                min-height: 18px;
                max-height: 18px;
            }}
            QFrame#spreadCenterColumn {{
                background-color: transparent;
                border: none;
                border-radius: 18px;
            }}
            QFrame#spreadValueFrame {{
                background-color: transparent;
                border: none;
                border-radius: 14px;
            }}
            QFrame#spreadValueInner {{
                background-color: transparent;
                border: none;
                border-radius: 14px;
            }}
            QFrame#spreadValueFrame[mode="select"][variant="neon_frame"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueInner[mode="select"][variant="neon_frame"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueFrame[mode="select"][variant="glass_slate"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueInner[mode="select"][variant="glass_slate"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueFrame[mode="select"][variant="signal_split"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueInner[mode="select"][variant="signal_split"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueFrame[mode="select"][variant="minimal_pro"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueInner[mode="select"][variant="minimal_pro"] {{
                background-color: transparent;
                border: none;
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="neon_frame"] {{
                background-color: {self._rgba(c_surface, 0.96)};
                border: 1px solid {self._rgba(c_accent, 0.45)};
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="glass_slate"] {{
                background-color: {self._rgba(c_surface, 0.96)};
                border: 1px solid {self._rgba(c_border, 0.74)};
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="signal_split"] {{
                background-color: {self._rgba(c_surface, 0.96)};
                border-top: 1px solid {self._rgba(c_border, 0.62)};
                border-bottom: 1px solid {self._rgba(c_border, 0.62)};
                border-left: 3px solid {self._rgba(c_border, 0.76)};
                border-right: 3px solid {self._rgba(c_border, 0.76)};
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="signal_split"][edgeTone="left_cheap"] {{
                border-left: 3px solid {self._rgba(c_success, 0.92)};
                border-right: 3px solid {self._rgba(c_danger, 0.92)};
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="signal_split"][edgeTone="right_cheap"] {{
                border-left: 3px solid {self._rgba(c_danger, 0.92)};
                border-right: 3px solid {self._rgba(c_success, 0.92)};
            }}
            QFrame#spreadValueFrame[mode="spread"][variant="minimal_pro"] {{
                background-color: transparent;
                border: 1px solid {self._rgba(c_border, 0.82)};
            }}
            QFrame#spreadValueInner[mode="spread"] {{
                background-color: {self._rgba(c_alt, 0.95)};
                border: none;
                border-radius: 12px;
            }}
            QFrame#spreadValueInner[mode="spread"][variant="minimal_pro"] {{
                background-color: transparent;
            }}
            QPushButton#spreadActionButton {{
                color: {c_primary};
                border-radius: 14px;
                font-size: 20px;
                font-weight: 700;
                padding: 6px 12px;
            }}
            QPushButton#spreadActionButton[variant="neon_frame"] {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self._rgba(c_accent, 0.20)},
                    stop: 1 {self._rgba(c_surface, 0.88)}
                );
                border: 1px solid {self._rgba(c_accent, 0.72)};
            }}
            QPushButton#spreadActionButton[variant="neon_frame"]:hover {{
                background-color: {self._rgba(c_accent, 0.28)};
            }}
            QPushButton#spreadActionButton[variant="glass_slate"] {{
                background-color: {self._rgba(c_surface, 0.78)};
                border: 1px solid {self._rgba(c_border, 0.74)};
            }}
            QPushButton#spreadActionButton[variant="glass_slate"]:hover {{
                background-color: {self._rgba(c_alt, 0.88)};
            }}
            QPushButton#spreadActionButton[variant="signal_split"] {{
                background-color: {self._rgba(c_surface, 0.84)};
                border: 1px solid {self._rgba(c_border, 0.74)};
            }}
            QPushButton#spreadActionButton[variant="signal_split"]:hover {{
                background-color: {self._rgba(c_alt, 0.92)};
            }}
            QPushButton#spreadActionButton[variant="minimal_pro"] {{
                background-color: transparent;
                border: 1px solid {self._rgba(c_border, 0.82)};
            }}
            QPushButton#spreadActionButton[variant="minimal_pro"]:hover {{
                background-color: {self._rgba(c_alt, 0.58)};
            }}
            QPushButton#spreadActionButton:disabled {{
                color: {c_muted};
                background-color: transparent;
            }}
            QLabel#spreadValueLabel {{
                background-color: transparent;
                border: none;
                font-size: 56px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }}
            QLabel#spreadValueLabel[variant="neon_frame"] {{
                color: {c_accent};
            }}
            QLabel#spreadValueLabel[variant="glass_slate"] {{
                color: {c_primary};
            }}
            QLabel#spreadValueLabel[variant="signal_split"] {{
                color: {c_primary};
            }}
            QLabel#spreadValueLabel[variant="minimal_pro"] {{
                color: {c_primary};
            }}
            QLabel#spreadValueLabel[empty="true"] {{
                color: {c_muted};
            }}
            QLabel#bidPriceText {{
                color: {theme_color('success')};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
            QLabel#askPriceText {{
                color: {theme_color('danger')};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
            QLabel#quoteQtyText {{
                color: {c_primary};
                font-size: 11px;
                font-weight: 700;
                padding-left: 4px;
            }}
            {self._strategy_theme_qss(
                c_surface=c_surface,
                c_border=c_border,
                c_alt=c_alt,
                c_primary=c_primary,
                c_muted=c_muted,
                c_success=c_success,
                c_danger=c_danger,
                c_accent=c_accent,
            )}
        """
        )

        popup_style = f"""
            QListView#pairPopup {{
                background-color: {theme_color('window_bg')};
                color: {c_primary};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 4px;
                outline: none;
                font-size: 12px;
            }}
            QListView#pairPopup::item {{
                padding: 6px 8px;
                border-radius: 6px;
            }}
            QListView#pairPopup::item:hover {{
                background-color: {self._rgba(c_accent, 0.20)};
                color: {c_primary};
            }}
            QListView#pairPopup::item:selected {{
                background-color: {theme_color('selection_bg_soft')};
                color: {c_accent};
                border: 1px solid {self._rgba(c_accent, 0.45)};
            }}
        """

        for column in self._iter_columns():
            if column.pair_completer is not None:
                popup = column.pair_completer.popup()
                popup.setObjectName("pairPopup")
                popup.setStyleSheet(popup_style)

        self._apply_spread_visual_variant()

    @staticmethod
    def _rgba(hex_color, alpha):
        color = str(hex_color or "").strip()
        if color.startswith("#") and len(color) == 7:
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                a = max(0.0, min(1.0, float(alpha)))
                return f"rgba({r}, {g}, {b}, {a:.3f})"
            except ValueError:
                return color
        return color
