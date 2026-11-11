# 音声タイミング調整パネルを既定で折りたたむ計画

## 要件

- 「音声タイミング調整」の設定 UI（元/追加のずらし・追加音声・開始位置・自動同期・追加再エンコード・
  プレビューに反映）を、ページ表示時に**既定で折りたたんだ状態**にする。
- 折りたたみはユーザーが明示的に開閉できること（状態は保存しない。再読み込みで既定の折りたたみに戻る）。

## 現状

- `web-qwen/index.html` の素材パネル内に、`<div class='field'>音声タイミング調整</div>`（プレビュー反映
  ボタン・状態表示）と `<div id='audioTimingBox'>`（ずらし・追加音声・自動同期などの設定）が続く。
- 既存の折りたたみ例として `<details class="meta-details">`（詳細メタデータ）がある（CSS クラス定義は
  なく、ブラウザ既定の details 表示）。

## 設計

- 上記の「音声タイミング調整」フィールドと `audioTimingBox` 全体を
  **`<details id='audioTimingDetails' class='audio-timing-details'>`** で囲み、**open 属性を付けない**
  （＝既定で折りたたみ）。
- `<summary>` に「音声タイミング調整」と短い補助文（例: ずらし・追加音声・プレビュー反映）を表示し、
  クリック／キーボード（Enter/Space）で開閉できる。
- 中の DOM（既存 ID・要素）は summary へ移す見出し以外は変更しない。既存の JS（disabled 制御・
  状態表示・イベント）はそのまま動く。
- 設定の永続化は行わない（要望どおり「デフォルトで折りたたみ」）。
- 見た目: summary は既存パネルの行に合わせた控えめなカード見出し（カーソル pointer）。既定マーカーは
  `list-style:none` と `::-webkit-details-marker{display:none}` で消し、開閉状態は `[open]` の
  背景／▼マーカーで示す。既存の `.as-sw` 用インライン style の近くに最小限の CSS を追加する。


## 設計詳細（実装仕様）

### マークアップ

```html
<details id='audioTimingDetails' class='audio-timing-details'>
  <summary>
    <span class='audio-timing-title'>音声タイミング調整</span>
    <span class='hint mono' id='audioTimingSummary'>元のみ / 元 0 ms / 追加 0 ms</span>
  </summary>
  <!-- 旧 field の中身（プレビュー反映ボタン・状態表示）を summary 直下に移設 -->
  <div class='field'>
    <div class='row'>…プレビューに反映 / 元に戻る / previewState…</div>
    <div class='hint' id='audioTimingState'>…</div>
  </div>
  <div id='audioTimingBox'>…既存のずらし・追加音声・自動同期・再エンコード…</div>
</details>
```

- 旧 `<div class='field' style='margin-top:12px'><label>音声タイミング調整</label>…` のうち **label は削除**し、
  同じ field 内のプレビュー行・状態表示は details の summary 直下（audioTimingBox の直前）へ移す。
- `open` 属性は付けない（既定で折りたたみ）。summary 全体（要約テキストを含む）が開閉トリガーになる。

### JavaScript

- `updateAudioTimingSummary()` を追加し、`updateAudioUI()` の末尾から呼ぶ。
  - mute: `消音（タイミング設定は使いません）`
  - それ以外: `<モード名> / 元 <msLabel> / 追加 <msLabel>`（msLabel は既存関数。0 でも表示）
- 既存の `updateAudioUI()` は初期化時に一度呼ばれているため、そのままで初期要約も確定する
  （実装時に boot/初期化で呼ばれていることを確認し、必要なら明示的に1回呼ぶ）。
- `<details>` の開閉はブラウザ標準に任せ、**追加のクリック/キーイベントは実装しない**。

### CSS

```css
.audio-timing-details{border:1px solid var(--line);border-radius:12px;background:#0d1119;padding:0 12px 10px;margin-top:14px}
.audio-timing-details>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 0;font-weight:800;user-select:none}
.audio-timing-details>summary:focus-visible{outline:2px solid rgba(74,163,255,.65);outline-offset:2px;border-radius:6px}
.audio-timing-details>summary::-webkit-details-marker{display:none}
.audio-timing-details>summary::before{content:'▶';display:inline-block;font-size:10px;color:var(--muted);transition:transform .15s}
.audio-timing-details[open]>summary::before{transform:rotate(90deg)}
.audio-timing-details>summary #audioTimingSummary{margin-left:auto;font-weight:400;min-width:0;overflow-wrap:anywhere}
```

## テスト（一本化）

- 静的ガード（`tests/check_ui_static.py`）:
  - details 開始タグを**属性順非依存**の `<details\b[^>]*\bid=['"]audioTimingDetails['"][^>]*>` で抽出し、
    そのタグ内に `\bopen\b` が無いこと。
  - summary に「音声タイミング調整」と `id='audioTimingSummary'` があること（文言は空でも要素存在を確認）。
  - 旧 `<label>音声タイミング調整</label>` が残っていないこと。
  - `audioTimingBox` が details（開始〜終了）内にあること。
- DOM 挙動（`tests/test_audio_ui_behaviour.js`）:
  - 初期ロード後 `audioTimingSummary` が空でなく、**モード名（元のみ/追加のみ/両方/同時）の
    いずれか**と「元」「追加」を含む。
  - `origShiftInp` に**既定と異なる値 250** を入力（input イベント）し、要約に `250` が
    反映される（同値 0 では変化しないため、必ず異なる値で検証する）。
  - mute に切り替えると要約が **「消音（タイミング設定は使いません）」と完全一致**する。
- 折りたたみ状態の操作: 既存の behaviour/smoke テストは DOM 上の同一要素を直接操作するため、
  details が閉じていても既存操作（disabled 制御・プレビュー反映）が壊れないことを回帰で確認する。
  実ブラウザでの開閉・キーボード操作はリリース前の手動確認項目とする。
- 回帰: 既存の全スイート（静的・settings・behaviour・timeline・smoke・unit）。

