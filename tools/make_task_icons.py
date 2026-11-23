"""Generate game-style colored emblems for the ok-dna task list.

Legacy: the icons under ``icons/`` are now hand-curated SVGs with a
transparent background. Running this script overwrites them with the older
generated set, so only run it when that variant is wanted.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "icons" / "tasks"


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="10" y1="7" x2="54" y2="57" gradientUnits="userSpaceOnUse">
      <stop stop-color="{c1}"/>
      <stop offset="1" stop-color="{c2}"/>
    </linearGradient>
  </defs>
{body}
</svg>
"""


ICONS = {
    "auto_expulsion": ("#D7384E", "#FF9A76", "#FFE0D6", """
  <path d="M32 5 55 32 32 59 9 32Z" fill="url(#g)" fill-opacity=".12"
        stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M32 14 46 32 32 50 18 32Z" fill="none" stroke="url(#g)" stroke-width="2.4" opacity=".8"/>
  <path d="M22 32h20M36 25l7 7-7 7" fill="none" stroke="url(#g)" stroke-width="3"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M9 32H3M55 32h6M32 5V1M32 59v4" stroke="url(#g)" stroke-width="2.4" stroke-linecap="round"/>
  <path d="M32 5l2.5 4-2.5 2.5L29.5 9z" fill="{a}"/>
"""),
    "auto_defence": ("#2E5BFF", "#7DD3FC", "#DCEBFF", """
  <path d="M32 6 54 14v16c0 12-9 21-22 28C19 51 10 42 10 30V14Z"
        fill="url(#g)" fill-opacity=".12" stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M32 15v34M21 22l11-7 11 7" fill="none" stroke="url(#g)" stroke-width="2.8"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M15 19c-4 6-4 14 0 20M49 19c4 6 4 14 0 20" fill="none" stroke="url(#g)"
        stroke-width="2.4" opacity=".65" stroke-linecap="round"/>
  <circle cx="32" cy="32" r="3.6" fill="{a}"/>
  <path d="M32 6l2.5 4L32 12.5 29.5 10z" fill="{a}"/>
"""),
    "auto_exploration": ("#16A34A", "#BEF264", "#ECFCCB", """
  <path d="M32 4l5 18 18 10-18 6-5 18-5-18-18-6 18-10z" fill="url(#g)" fill-opacity=".14"
        stroke="url(#g)" stroke-width="2.6" stroke-linejoin="round"/>
  <circle cx="32" cy="32" r="12" fill="none" stroke="url(#g)" stroke-width="2.4"/>
  <path d="M38 22 34 34 22 38 26 26z" fill="{a}" stroke="url(#g)" stroke-width="1.8" stroke-linejoin="round"/>
  <circle cx="46" cy="46" r="2" fill="{a}"/>
"""),
    "auto_mediation": ("#0D9488", "#FDE68A", "#FFF7D6", """
  <path d="M32 7 57 32 32 57 7 32Z" fill="url(#g)" fill-opacity=".08" stroke="url(#g)" stroke-width="2.6"/>
  <circle cx="32" cy="32" r="14" fill="none" stroke="url(#g)" stroke-width="2.6"/>
  <path d="M32 18a7 7 0 0 1 0 14 7 7 0 0 1 0 14" fill="none" stroke="url(#g)" stroke-width="2.8"/>
  <path d="M32 18a7 7 0 0 0 0 14 7 7 0 0 0 0 14" fill="none" stroke="url(#g)" stroke-width="2.8" opacity=".55"/>
  <circle cx="32" cy="25" r="2.2" fill="{a}"/>
  <circle cx="32" cy="39" r="2.2" fill="#fff" opacity=".85"/>
  <path d="M7 32H2M57 32h5M32 7V2M32 57v5" stroke="url(#g)" stroke-width="2.2"
        stroke-linecap="round" opacity=".7"/>
"""),
    "auto_hedge": ("#F97316", "#FDE68A", "#FFEDD5", """
  <path d="M8 20c7-1 12 2 16 9M8 44c7 1 12-2 16-9" fill="none" stroke="url(#g)"
        stroke-width="2.8" stroke-linecap="round"/>
  <path d="M16 15c-5 7-5 27 0 34M22 12c-6 9-6 31 0 40" fill="none" stroke="url(#g)"
        stroke-width="2.2" opacity=".5" stroke-linecap="round"/>
  <path d="M28 16 42 32 28 48" fill="none" stroke="url(#g)" stroke-width="3.4" stroke-linejoin="round"/>
  <path d="M40 32h16M48 25l7 7-7 7" fill="none" stroke="url(#g)" stroke-width="3.2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M58 32l3-2.5V34.5z" fill="{a}"/>
"""),
    "auto_mijin": ("#7C3AED", "#F0ABFC", "#F5D0FE", """
  <circle cx="32" cy="32" r="25" fill="url(#g)" fill-opacity=".10" stroke="url(#g)" stroke-width="2.6"/>
  <circle cx="32" cy="32" r="18" fill="none" stroke="url(#g)" stroke-width="2.2" opacity=".85"/>
  <g stroke="url(#g)" stroke-width="2" opacity=".75">
    <path d="M32 7v13M32 44v13M7 32h13M44 32h13M14 14l9 9M41 41l9 9M50 14l-9 9M23 41l-9 9"/>
  </g>
  <path d="M32 16l3.5 12.5L48 32l-12.5 3.5L32 48l-3.5-12.5L16 32l12.5-3.5z" fill="{a}"
        opacity=".95" stroke="#fff" stroke-opacity=".35" stroke-width="1"/>
  <path d="M24 22c3-3 7-4 10-2M48 36c-3 4-8 6-12 4" fill="none" stroke="#fff" stroke-width="1.6" opacity=".55"/>
  <path d="M32 49 24 58l3-1-4 5M32 15 40 6l-3 1 4-5" fill="none" stroke="{a}" stroke-width="1.8" stroke-linecap="round"/>
  <circle cx="32" cy="32" r="2.5" fill="#fff"/>
"""),
    "auto_letter": ("#4F86C6", "#E0F2FE", "#D6ECFF", """
  <defs>
    <radialGradient id="letterBg" cx=".42" cy=".36" r=".72">
      <stop stop-color="#2A507B"/>
      <stop offset="1" stop-color="#071321"/>
    </radialGradient>
    <linearGradient id="letterSilver" x1="12" y1="10" x2="52" y2="54">
      <stop stop-color="#FFFFFF"/>
      <stop offset=".55" stop-color="#D7E8F8"/>
      <stop offset="1" stop-color="#7FA8CC"/>
    </linearGradient>
  </defs>
  <circle cx="32" cy="32" r="27" fill="url(#letterBg)" stroke="#A9CBE8" stroke-width="2.2"/>
  <circle cx="32" cy="32" r="21" fill="none" stroke="#A9CBE8" stroke-opacity=".55" stroke-width="1.6"/>
  <path d="M46 9 49 12 22 43 17 38Z" fill="url(#letterSilver)"/>
  <path d="M46 9 49 12 23 41" stroke="#FFFFFF" stroke-width="1" opacity=".6"/>
  <path d="M13 35 27 49" stroke="url(#letterSilver)" stroke-width="4" stroke-linecap="round"/>
  <circle cx="13" cy="35" r="2.6" fill="#7DD3FC"/>
  <circle cx="27" cy="49" r="2.6" fill="#7DD3FC"/>
  <path d="M20 41 15 46" stroke="url(#letterSilver)" stroke-width="3.5" stroke-linecap="round"/>
  <circle cx="14" cy="47" r="3" fill="#F8FCFF" stroke="#7FA8CC" stroke-width="1"/>
  <path d="M17 13l1.5 3 3 .5-2.2 2 .5 3-2.8-1.6-2.8 1.6.5-3-2.2-2 3-.5z"
        fill="#F8FCFF" opacity=".9"/>
  <circle cx="50" cy="44" r="1.6" fill="#7DD3FC"/>
"""),
    "auto_theatre": ("#B76E79", "#FFE3B3", "#7DD3FC", """
  <path d="M8 57V28C8 14 19 5 32 5s24 9 24 23v29Z" fill="#0B1628" fill-opacity=".18"
        stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M15 57V29c0-10 7-17 17-17s17 7 17 17v28Z" fill="#5EB8FF" fill-opacity=".14"
        stroke="url(#g)" stroke-width="2.2"/>
  <path d="M23 50V35c0-2 1.5-4 3.5-4S30 33 30 35v15M30 50V31c0-2 1.5-4 3.5-4S37 29 37 31v19M37 50V34c0-2 1.5-4 3.5-4s3.5 2 3.5 4v16"
        fill="none" stroke="url(#g)" stroke-width="2.4" stroke-linecap="round"/>
  <path d="M19 57V30M45 57V30" stroke="url(#g)" stroke-width="2.2" opacity=".7"/>
  <path d="M8 57h48" stroke="url(#g)" stroke-width="3" stroke-linecap="round"/>
  <g fill="#fff" opacity=".9"><circle cx="20" cy="18" r="1.2"/><circle cx="42" cy="14" r="1.2"/>
    <circle cx="38" cy="24" r="1"/><circle cx="24" cy="12" r="1"/></g>
  <path d="M32 8l2 4-2 2-2-2z" fill="{a}"/>
"""),
    "auto_hunt_moon": ("#D97706", "#FDE68A", "#FFEDD5", """
  <path d="M8 58V29C8 14 18 6 32 6s24 8 24 23v29Z" fill="url(#g)" fill-opacity=".10"
        stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M15 58V30c0-10 7-17 17-17s17 7 17 17v28" fill="none" stroke="url(#g)"
        stroke-width="2.2" opacity=".75"/>
  <circle cx="32" cy="34" r="11" fill="{a}" fill-opacity=".18" stroke="url(#g)" stroke-width="2.6"/>
  <path d="M32 25c4 0 7 3.5 7 9s-3 9-7 9-7-3.5-7-9 3-8 7-8 6 3 6 8" fill="none"
        stroke="url(#g)" stroke-width="2.2" stroke-linecap="round"/>
  <g stroke="url(#g)" stroke-width="2" stroke-linecap="round">
    <path d="M32 21v-5M32 52v-5M19 34h-5M50 34h-5M23 25l-3-3M44 25l3-3M23 43l-3 3M44 43l3 3"/>
  </g>
  <path d="M13 25c-6 3-8 10-5 16 2-4 5-5 8-3-2 5 0 9 4 12 0-6 3-9 7-10-3-3-4-8-2-12-4 0-8-1-12-3z"
        fill="{a}" opacity=".75"/>
  <path d="M51 25c6 3 8 10 5 16-2-4-5-5-8-3 2 5 0 9-4 12 0-6-3-9-7-10 3-3 4-8 2-12 4 0 8-1 12-3z"
        fill="{a}" opacity=".55"/>
  <path d="M32 7l2 4-2 2-2-2z" fill="#fff"/>
"""),
    "auto_nightmare": ("#7A1620", "#FF6B6B", "#FFD9C8", """
  <path d="M32 4 38 20 54 12 45 28 60 32 45 36 54 52 38 44 32 60 26 44 10 52 19 36 4 32 19 28 10 12 26 20Z"
        fill="#1B0B10" stroke="url(#g)" stroke-width="2.2" stroke-linejoin="round"/>
  <path d="M32 18c-8 5-12 9-12 14s4 9 12 14c8-5 12-9 12-14s-4-9-12-14z" fill="none"
        stroke="url(#g)" stroke-width="2.2"/>
  <circle cx="32" cy="32" r="7" fill="url(#g)"/>
  <circle cx="32" cy="32" r="3" fill="#12070A"/>
  <path d="M32 18v-5M32 46v5" stroke="{a}" stroke-width="1.5" opacity=".8"/>
  <path d="M18 20l3-3 3 3-3 3zM43 41l3-3 3 3-3 3z" fill="{a}" opacity=".65"/>
"""),
    "auto_fish_leisure": ("#14B8A6", "#BEF264", "#FDE68A", """
  <path d="M32 8c13 0 24 10 24 24S45 56 32 56 8 46 8 32 19 8 32 8z" fill="none"
        stroke="url(#g)" stroke-width="2.2" opacity=".45"/>
  <path d="M14 34c6-9 17-10 25-3 2 2 4 2 6 1M14 34c6 9 17 10 25 3 2-2 4-2 6-1"
        fill="none" stroke="url(#g)" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M45 31l6-4v10z" fill="{a}"/>
  <circle cx="22" cy="32" r="1.8" fill="{a}"/>
  <path d="M46 9 28 28M43 7l5 4" stroke="url(#g)" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M34 29v9" stroke="{a}" stroke-width="2" stroke-linecap="round"/>
  <circle cx="34" cy="40" r="3.2" fill="{a}" stroke="#fff" stroke-width=".9"/>
  <path d="M18 49c4 2 8 2 12 0" stroke="url(#g)" stroke-width="2" stroke-linecap="round" opacity=".6"/>
"""),
    "auto_fish": ("#1D4ED8", "#67E8F9", "#DBEAFE", """
  <path d="M8 32c10-12 24-12 34 0-10 12-24 12-34 0z" fill="url(#g)" fill-opacity=".10"
        stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M42 32l12-8v16z" fill="url(#g)" opacity=".8"/>
  <circle cx="19" cy="29" r="2" fill="{a}"/>
  <path d="M54 12v18a7 7 0 0 1-14 0" fill="none" stroke="{a}" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M12 48c10 4 20 4 30 0" fill="none" stroke="url(#g)" stroke-width="2.2" stroke-linecap="round" opacity=".5"/>
"""),
    "auto_skill": ("#8B5CF6", "#22D3EE", "#EDE9FE", """
  <path d="M32 4l5.5 19 19 9-19 5.5-5.5 22.5-5.5-22.5L7 32l19-9z" fill="url(#g)"
        fill-opacity=".18" stroke="url(#g)" stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M32 14l3 12 12 6-12 3-3 14-3-14-12-3 12-6z" fill="url(#g)" opacity=".9"
        stroke="#fff" stroke-opacity=".45" stroke-width="1"/>
  <ellipse cx="32" cy="32" rx="25" ry="10" transform="rotate(-28 32 32)"
           fill="none" stroke="{a}" stroke-width="2.2"/>
  <circle cx="55" cy="18" r="2" fill="{a}"/>
  <circle cx="9" cy="45" r="1.6" fill="#fff" opacity=".9"/>
"""),
}


GROUP_ICONS = {
    "activity": ("#8B5CF6", "#F0ABFC", "#FDE68A", """
  <path d="M32 5 39 23 57 31 39 39 32 59 25 39 7 31 25 23Z" fill="url(#g)" fill-opacity=".10"
        stroke="url(#g)" stroke-width="3" stroke-linejoin="round"/>
  <path d="M37 10 42 24 55 29 42 34 37 48 32 34 19 29 32 24Z" fill="none"
        stroke="url(#g)" stroke-width="2.2" stroke-linejoin="round" opacity=".65"/>
  <path d="M32 22 35 29 42 32 35 35 32 42 29 35 22 32 29 29Z" fill="{a}"/>
"""),
    "daily": ("#3B82F6", "#7DD3FC", "#DBEAFE", """
  <path d="M18 19h28v29H18z" fill="url(#g)" fill-opacity=".10" stroke="url(#g)"
        stroke-width="2.8" stroke-linejoin="round"/>
  <path d="M32 8l5-5 5 5-5 5z" fill="url(#g)" opacity=".9"/>
  <path d="M32 25v12M32 41v2" stroke="url(#g)" stroke-width="4" stroke-linecap="round"/>
  <path d="M32 49l3 3-3 3-3-3z" fill="{a}"/>
  <path d="M22 24v18M42 24v18" stroke="url(#g)" stroke-width="1.2" opacity=".35"/>
"""),
    "leisure": ("#10B981", "#6EE7B7", "#D1FAE5", """
  <path d="M32 7v49" stroke="url(#g)" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M32 13l4 4-4 4-4-4z" fill="{a}"/>
  <path d="M32 45l4 4-4 4-4-4z" fill="{a}"/>
  <path d="M31 20C20 20 12 26 12 36c0 8 7 13 15 14" fill="none" stroke="url(#g)" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M33 20c11 0 19 6 19 16 0 8-7 13-15 14" fill="none" stroke="url(#g)" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M14 47c7 5 29 5 36 0" fill="none" stroke="url(#g)" stroke-width="2.6" stroke-linecap="round"/>
  <path d="M22 28c-4 6-4 13 0 18M42 28c4 6 4 13 0 18" fill="none" stroke="url(#g)"
        stroke-width="2" opacity=".55" stroke-linecap="round"/>
  <path d="M28 32v12M36 32v12" stroke="url(#g)" stroke-width="1.5" opacity=".35"/>
"""),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (c1, c2, accent, body) in ICONS.items():
        body = body.replace("{a}", accent)
        (OUT / f"{name}.svg").write_text(SVG.format(c1=c1, c2=c2, body=body), encoding="utf-8")
    group_out = ROOT / "icons" / "groups"
    group_out.mkdir(parents=True, exist_ok=True)
    for name, (c1, c2, accent, body) in GROUP_ICONS.items():
        body = body.replace("{a}", accent)
        (group_out / f"{name}.svg").write_text(SVG.format(c1=c1, c2=c2, body=body), encoding="utf-8")
    print(f"wrote {len(ICONS)} task icons and {len(GROUP_ICONS)} group icons")


def preview():
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PIL import Image, ImageDraw

    QGuiApplication.instance() or QGuiApplication([])
    cell_w, cell_h = 150, 128
    columns = 4
    rows = (len(ICONS) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "#F5F7FB")
    draw = ImageDraw.Draw(sheet)
    for index, name in enumerate(ICONS):
        renderer = QSvgRenderer(QByteArray((OUT / f"{name}.svg").read_bytes()))
        image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, 96, 96))
        painter.end()
        tmp = OUT / f"_{name}.png"
        image.save(str(tmp))
        icon = Image.open(tmp).convert("RGBA")
        tmp.unlink(missing_ok=True)
        x = (index % columns) * cell_w + (cell_w - 96) // 2
        y = (index // columns) * cell_h + 4
        sheet.paste(icon, (x, y), icon)
        label = name.replace("auto_", "").replace("_", " ")
        draw.text(((index % columns) * cell_w + 8, (index // columns) * cell_h + 104),
                  label, fill="#4B5563")
    output = OUT / "_preview.png"
    sheet.save(output)
    print(output)

    group_out = ROOT / "icons" / "groups"
    group_sheet = Image.new("RGB", (cell_w * len(GROUP_ICONS), cell_h), "#F5F7FB")
    group_draw = ImageDraw.Draw(group_sheet)
    for index, name in enumerate(GROUP_ICONS):
        renderer = QSvgRenderer(QByteArray((group_out / f"{name}.svg").read_bytes()))
        image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, 96, 96))
        painter.end()
        tmp = group_out / f"_{name}.png"
        image.save(str(tmp))
        icon = Image.open(tmp).convert("RGBA")
        tmp.unlink(missing_ok=True)
        x = index * cell_w + (cell_w - 96) // 2
        group_sheet.paste(icon, (x, 4), icon)
        group_draw.text((index * cell_w + 8, 104), name, fill="#4B5563")
    group_output = group_out / "_preview.png"
    group_sheet.save(group_output)
    print(group_output)


if __name__ == "__main__":
    main()
    if "--preview" in sys.argv:
        preview()
