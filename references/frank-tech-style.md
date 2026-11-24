# Frank 科普风 · 16:9 横屏深色科技 MG 配方

> **一句话**：把一段 AI 知识科普口播做成 **16:9 横屏（1920×1080）深色科技 MG 动画**，
> 图形跟随旁白**卡点弹出**，字幕固定**在画面下方**，整体**炫酷但克制**。
>
> 本文是「博主科普讲解动画生成器」的一个**成品配方**（不是独立技能）：复用本技能既有的
> ASR 识别 + 节拍锚点 + 动效库 + 逐帧渲染管线，只固化「画布 / 配色 / 时序 / 字幕带」四层约定。

---

## 0. 适用 / 不适用

- **适用**：AI 科普、知识类口播短视频/长视频；要「深色科技感 + 图形跟节奏弹出」；
  手上有**自录人声 MP3**（走 `asr_build.py`）或**纯文案**（走 `tts_build.py`）。
- **不适用**：真人口播、实拍、手绘白板、卡通画风、复刻他人素材 —— 本配方一律**原创画面**，
  不搬运任何原视频素材。

---

## 1. 画布（硬约定）

| 项 | 值 |
|---|---|
| 画布 | **16:9 横屏 1920×1080** |
| 建项目 | `--width 1920 --height 1080` |
| 帧率 / 档位 | 默认 30fps，`--profile balanced`（1080p30 + 快门运动模糊） |
| 字幕 | **底部字幕带**（预留 y≈900–1040 的安全带，元素不许侵入） |
| 封面 | `cover_169.png`（横屏主封面），竖版封面不需要 |

> 与 9:16 竖屏配方的差异只在这一节：**竖屏把宽高对调、字幕带改成 y≈1750–1900**。
> 其余配色/时序/动效约定完全一致。

---

## 2. 配色（深色霓虹 · 克制）

**唯一配色纪律：近黑底 + 三种霓虹强调色，全片各只用一次语义。**

| 角色 | 色值 | 用途 |
|---|---|---|
| 背景底 | `#08090c`（近黑） | 全局背景，可叠加极弱 radial vignette 让中心更亮 |
| 主强调 | `#00f0ff`（青霓虹） | 大标题描边、关键图形主色、进度条 |
| 次强调 | `#ff2bd6`（品红） | 副标、强调词、次要图形 |
| 点缀 | `#ffb547`（琥珀橙） | 数字跳动、焦点卡、CTA、品牌收尾 |
| 正文 / meta | `#f5f5f7` / `#8a8a94` | 正文近白、meta 行灰（等宽字体） |

纪律：

- **全片只用一个语义强调色**做主角（默认青 `#00f0ff`），品红/琥珀只做点缀，**别三色等权**。
- 文字对比度靠「近白正文 on 近黑底」保证，霓虹色只用于**描边/图形/关键字**，不用来写正文段落。
- 配色走 `theme.css` 变量（或 `make_theme.py` 生成的 theme），**画面内禁止色值字面量**。

---

## 3. 时序：图形跟随旁白「卡点弹出」

这是本配方的灵魂。**每一句旁白 = 一组图形，图形在旁白吐字的真实时刻弹出**，不是按字数插值。

实现两条路（二选一，均走本技能既有管线）：

- **A. 自录 MP3**：`asr_build.py`（faster-whisper）产出**词级时间戳** `boundaries`，
  画面节拍 `B('块文本')` 直接锚在**真实吐字时刻**上。
- **B. 文案配音**：`tts_build.py`（edge-tts WordBoundary）产出词边界，同源同构。

节拍写法（`narration.json` 里每个块都是吐字时刻的锚）：

```js
// 开场 0.0s 起，主标题「落下」；旁白说到「神经元」这个词的瞬间，节点图形弹出
B('开场标题')   // 锚在首句旁白的真实起点
B('神经元节点') // 锚在「神经元」三个字被念出口的那一刻
```

**卡点弹出 = 用 `assets/motion.js` 的出场动效，配合 `B()` 节拍器**：

| 动效 | 函数 | 何时用 |
|---|---|---|
| 词「落下」 | `riseWord(t, t0)` | 关键词/标题，弹簧上升 + 轻放大，不透明领先 |
| 卡片弹入 | `springIn(t, t0)` | 图形卡片、图例、说明框 |
| 逐字落下 | `dropLetters(t, t0, i)` | 大字标题逐字砸下，速度压扁 |
| 硬切词 | `burstWord(t, list)` | 需要「一记一记砸」的关键数字 |
| 落地余震 | `landHit(t, tHit)` | 图形落定那一下的压扁+回弹 |

> 反例要避免：用纯 opacity 淡入读起来像 PPT（`riseWord` 自带位移弹簧，专治这个）。
> 一个 beat 不许「替换」上一个 —— 用 `morphBox` / `irisOpen` / `camTrack` 让元素跨边界延续。

---

## 4. 字幕带（下方固定）

- 字幕**固定在画面下方**（16:9 画布 y≈900–1040 安全带），**不随图形滚动、不居中遮挡主体**。
- 词级硬字幕，**中文 ≤16 字/块**，逐句对齐人声（`subs.py` 产出 `subs.json` + `beats.js` + `srt/vtt`）。
- 样式：近黑半透明底条 + 近白正文；关键术语可用青 `#00f0ff` 高亮（保持克制，不整句染色）。

---

## 5. 完整流程（照本技能主流程走，只改画布）

```bash
PY=<venv python 绝对路径>
# 0. 建项目（★ 16:9 横屏）
"$PY" <skill>/scripts/new_project.py <dir> <slug> --topic "主题" --width 1920 --height 1080
# 1. 配音方案（问用户 edge / 火山）
"$PY" <skill>/scripts/tts_setup.py --project .
# 2a. 输入 A：自录 MP3 → ASR（★ 音频驱动，本配方首选）
"$PY" <skill>/scripts/asr_build.py --project . --audio "我的口播.mp3" --model small
# 2b. 输入 B：文案自动配音
"$PY" <skill>/scripts/tts_build.py --project .
# 3. 时间轴 + 字幕
"$PY" <skill>/scripts/timeline_build.py --project .
"$PY" <skill>/scripts/subs.py --project .
"$PY" <skill>/scripts/check_beats_refs.py --project .
# 4. 风格编排（读解说词，自动挑「深色科技」类主风格）
"$PY" <skill>/scripts/style_director.py --project .
# 5. 确认闸门 + 渲染通道确认（★ 不许跳过）
"$PY" <skill>/scripts/gate_check.py --project .
"$PY" <skill>/scripts/gate_check.py --project . --phase render
# 6. 体检
"$PY" <skill>/scripts/lint_frames.py --project .
node <skill>/scripts/check_layout.mjs .
# 7. 渲染（先打样 --preview，用户确认后全片）
node <skill>/scripts/render_video.mjs . --profile draft --preview 30
node <skill>/scripts/render_video.mjs . --profile balanced --audio audio/narration-full.mp3 --png-fast
# 8. 体检 + 封面
"$PY" <skill>/scripts/qc_check.py --project .
node <skill>/scripts/cover_build.mjs .
```

---

## 6. 深色科技风从哪几个模板取

风格库（`references/style-catalog.md`）里**深色霓虹基因**集中在这些模板，
做「Frank 风」时优先从它们**吸纳配色/字体/时序三层**（不搬模板画面，画面语言用 `motion.js` 重写）：

- **故障艺术标题帧**（glitch / 标题卡）—— 近黑底 + 霓虹描边大字，开场的强记忆点。
- **创意电压分屏帧 / 电光工作室分屏帧** —— 深底霓虹分屏，正文+图形的节奏感。
- **Swiss Grid / Kinetic Type** —— 深色底 + 等宽字体 meta 行 + 网格，克制的数据/文字排版。

> 判据：成片能被认出「这是某个模板」= 吸纳过头；只能说「配色像、节奏像」= 深度对了。

---

## 7. 禁止项（本配方红线）

- ❌ 真人出镜、手绘白板、卡通/动漫画风。
- ❌ 盗用原视频素材、搬运他人画面 —— 全部画面原创（HTML/CSS/GSAP 现场生成）。
- ❌ 高饱和杂色、多余装饰、贴纸水印、多余 BGM。
- ❌ 复杂纹理堆叠 —— 深色科技感靠「近黑底 + 克制霓虹描边 + 网格/扫描线」，不是靠贴图。
