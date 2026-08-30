# -*- coding: utf-8 -*-
"""生成建仓计划长图（微信可分享 PNG）。深色卡片 + 红涨绿跌（目标红/止损绿）。"""
import json
from PIL import Image, ImageDraw, ImageFont

# ---- 字体 ----
F_REG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
F_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


def font(path, size):
    return ImageFont.truetype(path, size)


# ---- 配色（A股红涨绿跌）----
BG = (13, 17, 23)          # #0d1117
CARD = (22, 27, 34)        # #161b22
BORDER = (48, 54, 61)      # #30363d
TEXT = (230, 237, 243)     # #e6edf3
SUB = (139, 148, 158)      # #8b949e
RED = (255, 71, 87)        # #ff4757 涨/目标/强势
GREEN = (0, 212, 170)      # #00d4aa 跌/止损
ORANGE = (255, 165, 2)     # #ffa502
BLUE = (88, 166, 255)      # #58a6ff
PURPLE = (188, 140, 255)   # #bc8cff

W = 1080
PAD = 44
CONTENT_W = W - PAD * 2

ROLE_COLOR = {
    "长期底仓": BLUE,
    "短线·首选": RED,
    "短线": ORANGE,
    "短线·备选": SUB,
    "科创·首选": RED,
    "科创": PURPLE,
}


def pct_color(p):
    return RED if p >= 0.8 else ORANGE


def draw_pill(d, x, y, h, text, bg, fg, f):
    """圆角徽章，返回文本右端 x。"""
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 22, y + h], radius=h // 2, fill=bg)
    d.text((x + 11, y + (h - f.size) / 2 - 2), text, font=f, fill=fg)
    return x + tw + 22


def main():
    plan = json.load(open("config/entry_plan.json", encoding="utf-8"))
    entries = plan["entries"]
    rules = plan["rules"]

    # 预计算总高度
    title_h = 200
    legend_h = 90
    card_h = 236
    gap = 20
    disc_h = 260
    footer_h = 80
    total_h = title_h + legend_h + (card_h + gap) * len(entries) + disc_h + footer_h

    img = Image.new("RGB", (W, total_h), BG)
    d = ImageDraw.Draw(img)

    f_title = font(F_BOLD, 52)
    f_sub = font(F_REG, 26)
    f_name = font(F_BOLD, 36)
    f_code = font(F_REG, 26)
    f_body = font(F_REG, 27)
    f_small = font(F_REG, 23)
    f_label = font(F_REG, 22)

    y = 0
    # ---- 标题区 ----
    d.rectangle([0, 0, W, title_h], fill=(16, 20, 27))
    # 渐变标题文字（近似：主标题橙红）
    d.text((PAD, 42), "量化建仓计划 · 7 只候选", font=f_title, fill=RED)
    d.text((PAD, 112), "数据截至 08-28 收盘 · 因子池 452 只 · 只碰因子分位≥60%强股", font=f_sub, fill=SUB)
    d.text((PAD, 146), "三批建仓 1/3+1/3+1/3（试仓 → 确认 → 突破）", font=f_sub, fill=TEXT)
    y = title_h

    # ---- 图例 ----
    d.rectangle([0, y, W, y + legend_h], fill=BG)
    lx = PAD
    lx = draw_pill(d, lx, y + 20, 30, "目标价(看涨)", RED, (255, 255, 255), f_label) + 24
    lx = draw_pill(d, lx, y + 20, 30, "止损价(看跌)", GREEN, (0, 0, 0), f_label) + 24
    draw_pill(d, lx, y + 20, 30, "强因子分位≥80%", RED, (255, 255, 255), f_label)
    y += legend_h

    # ---- 卡片 ----
    for e in entries:
        d.rounded_rectangle([PAD, y, W - PAD, y + card_h], radius=18, fill=CARD, outline=BORDER, width=2)
        cx = PAD + 28
        ty = y + 24
        # 第一行：名称 + 代码 + 角色徽章
        d.text((cx, ty), e["name"], font=f_name, fill=TEXT)
        name_w = d.textlength(e["name"], font=f_name)
        d.text((cx + name_w + 16, ty + 9), e["code"], font=f_code, fill=SUB)
        role_c = ROLE_COLOR.get(e["role"], SUB)
        role_w = d.textlength(e["role"], font=f_label)
        d.rounded_rectangle([W - PAD - 28 - role_w - 24, ty + 4, W - PAD - 28, ty + 4 + 34],
                            radius=17, fill=role_c)
        d.text((W - PAD - 28 - role_w - 12, ty + 8), e["role"], font=f_label, fill=(255, 255, 255))

        # 第二行：分位 + 现价 + 状态
        ty2 = ty + 56
        pc = pct_color(e["pct_rank"])
        d.text((cx, ty2), "因子分位", font=f_body, fill=SUB)
        d.text((cx + 96, ty2), f"{e['pct_rank']*100:.1f}%", font=f_body, fill=pc)
        d.text((cx + 260, ty2), "现价", font=f_body, fill=SUB)
        d.text((cx + 320, ty2), f"{e['price']:.2f}", font=f_body, fill=TEXT)
        d.text((cx + 520, ty2), e["status"], font=f_body, fill=SUB)

        # 第三行：买点 + 加仓确认
        ty3 = ty2 + 44
        d.text((cx, ty3), "第一买点", font=f_body, fill=SUB)
        d.text((cx + 96, ty3), f"{e['entry_low']} ~ {e['entry_high']}", font=f_body, fill=ORANGE)
        d.text((cx + 400, ty3), "确认", font=f_body, fill=SUB)
        d.text((cx + 452, ty3), e["confirm"], font=f_body, fill=TEXT)

        # 第四行：止损(绿) + 目标(红)
        ty4 = ty3 + 44
        d.text((cx, ty4), "止损", font=f_body, fill=SUB)
        d.text((cx + 96, ty4), f"{e['stop_loss']}", font=f_body, fill=GREEN)
        d.text((cx + 260, ty4), "目标", font=f_body, fill=SUB)
        d.text((cx + 320, ty4), f"{e['target']}", font=f_body, fill=RED)
        d.text((cx + 520, ty4), e["account"], font=f_small, fill=SUB)

        # 备注
        ty5 = ty4 + 44
        d.text((cx, ty5), e["note"], font=f_small, fill=SUB)

        y += card_h + gap

    # ---- 纪律区 ----
    d.rounded_rectangle([PAD, y, W - PAD, y + disc_h], radius=18, fill=CARD, outline=BORDER, width=2)
    cx = PAD + 28
    dy = y + 26
    d.text((cx, dy), "执行纪律", font=f_name, fill=ORANGE)
    dy += 52
    for i, line in enumerate(rules["discipline"]):
        d.text((cx, dy + i * 40), f"{i+1}. {line}", font=f_small, fill=TEXT)

    y += disc_h + 24
    # ---- footer ----
    d.text((PAD, y), "量化工作台 · 自动生成 · 止损/目标价随行情每日更新", font=f_small, fill=SUB)

    img.save("entry-plan-20260831.png")
    print(f"已生成 entry-plan-20260831.png  尺寸 {W}x{total_h}")


if __name__ == "__main__":
    main()
