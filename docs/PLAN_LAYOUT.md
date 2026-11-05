# 長いファイル名／動画選択で本文側の表示倍率が変わる問題 ― 調査と修正計画（v0.4）

作成: 2026-11-06 / 対象: Qwen 版（web-qwen/index.html）と web 版（web/）
改訂: v0.1〜v0.3 へのレビュー指摘（body をクリップ祖先から除外・fixed 除外・診断タイミング）を反映。旧: v0.1/v0.2 へのレビュー指摘（診断基準・.viewer video・viewport meta・スクロールコンテナ除外ほか）を反映。

## 1. 症状

- 長いファイル名の動画を選ぶと、**ヘッダーより下（ステージ・設定・一覧）の表示倍率が変わり**、まるでブラウザのズームを変えたように見える。
- 前回の対策（`html, body { overflow-x: hidden }`）でヘッダーの見た目の変化は収まったが、**本文側の倍率変化は残っている**。

## 2. 調査（Gemini 3.8 Flash + Web 検索）

出典:

- MDN Web Docs: overflow-wrap — https://developer.mozilla.org/ja/docs/Web/CSS/overflow-wrap
- MDN Web Docs: ビューポートメタタグ — https://developer.mozilla.org/ja/docs/Web/HTML/Viewport_meta_tag
- web.dev: Responsive web design basics — https://web.dev/articles/responsive-web-design-basics

要点:

1. **仕組み**: 改行できない長い文字列（長いファイル名・パス・URL）や**置換要素（img/video）の固有幅**は、その要素の **min-content 幅**を押し上げる。親（1fr トラック等）は min-content より狭くなれないため、**レイアウトビューポート（ICB＝ページの論理幅）が端末の画面幅より広がる**。
2. **`overflow-wrap: anywhere` は min-content の計算に折り返しを反映する**。`break-word` は折り返すが **min-content には反映されない**。`word-break: break-all` は min-content をほぼ1文字幅まで下げる。
3. **flex/grid アイテムの既定 `min-width: auto`** が「内容幅未満への縮小」を禁止する。`min-width: 0` の明示が必要。
4. **親の `overflow-x: hidden` は根治にならない**。はみ出しの「見え方」を消すだけで、min-content による押し広げは防げない（今回まさにこれ）。

### 2.1 viewport meta の現状と帰結（v0.2 追加）

| UI | meta | 帰結 |
|---|---|---|
| Qwen | `width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no` | `initial-scale` / `maximum-scale` 明示時は、現行ブラウザは overflow でも**自動縮小せずパン**が一般的。ただし ICB が広がると CSS px 基準で描画が小さくなり「倍率が変わった」ように見え得る。`user-scalable=no` は iOS が無視し、アクセシビリティ上も削除が望ましい |
| web | `width=device-width, initial-scale=1, viewport-fit=cover` | 自動縮小の対象になり得る |

→ **機構の断定は実機計測（§4）で行う**。`user-scalable=no` / `maximum-scale=1.0` の削除も本計画で提案する（ピンチズーム許可は a11y 改善）。

## 3. コード調査で見つかった溢れ候補（v0.2 更新）

| 優先 | 場所 | 現状 | なぜ溢れるか | 対策 |
|---|---|---|---|---|
| **1** | `.viewer video`（qwen L84-85） | `.viewer{display:grid;place-items:center}` + `video{width:100%;height:100%;object-fit:contain}` | 置換要素の自動最小サイズは**固有幅（動画の実寸。4K なら 3840px）**。`.stage` が 860px 以下で `1fr` のためトラックが実寸まで拡張 → **ICB が数千 px に拡大**。ファイル名より有力な主因 | `.viewer video{max-width:100%;min-width:0}`、`.stage` / `.viewer` のトラックを `minmax(0,1fr)` に |
| **2** | `.crop-grid`（4列） | `repeat(4, 1fr)` + input | input の固有幅（約170px）×4 → 360px 端末で 680px 超 | トラックを `minmax(0,1fr)`、`.inp` に `min-width:0`、狭幅は2列 |
| **3** | `.opt-grid`（2列） / `.inout`（2列） | `1fr 1fr` + select/input | 2×170 + 余白で 360px を超え得る | 同上 |
| **4** | `.sheet-foot`（qwen L181） | `display:flex` + `.inp{width:100%}` の input×2 + ボタン。`flex-wrap` なし | input 2個の `min-width:auto` で合計 340px 超 → モーダル幅 `min(560px,100%)` を突き抜け | `flex-wrap: wrap`、input を `flex:1 1 120px; min-width:0` に |
| 5 | `.src-sub span` | `white-space: nowrap` のみ | flex アイテムの `min-width:auto` | `min-width:0` + ellipsis |
| 6 | `#srcDetail` | `white-space: pre-wrap` | pre-wrap は空白でしか折らない | `overflow-wrap: anywhere` |
| 7 | `.chip .nm` | `max-width: 56vw` | vw 依存 | `max-width: min(56vw, 100%)` |
| 8 | nowrap 系（`.badge` / `.tbtn` / `.entry .sz` / `.srcbar .btn`） | `white-space:nowrap` | 短い文言のみで実害は低い | `min-width:0` を統一付与 |
| — | `.kv` | `auto 1fr` + dd は `break-all` | **押し広げは起きない**（break-all が min-content を下げる）。v0.1 の「低〜中」は過大評価 | `minmax(0,1fr)` への統一のみ（任意） |
| — | `.logbox` / `.frame-strip` | `overflow:auto` | スクロールコンテナは縮小可 | 維持 |
| — | `.src-name` / `.entry .nm` | `nowrap + ellipsis + min-width:0` | 4点セット済み | 維持 |

**結論（更新）**: 主因は「**置換要素（video）とフォーム部品を含む 1fr グリッドが `min-width:auto` のため縮小できず、ICB を押し広げている**」こと。ファイル名は引き金の一つに過ぎない可能性が高い。§4 の診断で確定してから修正する。

## 4. 診断（実機で特定する）— 最優先（v0.2 で基準を修正）

**v0.1 の誤り**: `documentElement.clientWidth` は ICB 拡張時には**拡張後の幅**を返すため、これを基準にすると何も検出できず受入基準も空虚に成立する（レビュー指摘 M1）。
**正しい基準**: `window.screen.width`（端末の CSS px 幅。DevTools の端末エミュレーションでは追従する）を使う。

`FENCE`js
(function () {
  var sw = window.screen.width;                       // 端末幅（ICB 拡張の影響を受けない）
  var de = document.documentElement;
  var vv = window.visualViewport;
  var report = {
    screenWidth: sw,
    clientWidth: de.clientWidth,                      // ICB が広がっていれば sw より大きい
    scrollWidth: de.scrollWidth,
    icbExpanded: de.clientWidth > sw + 1,
    visualScale: vv ? vv.scale : null,
    visualWidth: vv ? Math.round(vv.width) : null,
    offenders: []
  };
  // body / html は「文書そのもの」であり、その overflow-x:hidden は ICB 押し広げを防げなかった
  // （まさに本件の症状）。よって body より内側の祖先だけをクリップ祖先とみなす。
  function inScrollContainer(el) {
    for (var p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      var ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll" || ox === "hidden" || ox === "clip") { return true; }
    }
    return false;
  }
  document.querySelectorAll("*").forEach(function (el) {
    var r = el.getBoundingClientRect();
    // スクロールコンテナの子孫は内側でスクロールするため ICB を押し広げない（誤検出を除外）
    var fixed = getComputedStyle(el).position === "fixed";   // fixed は ICB を押し広げない
    if (!fixed && !inScrollContainer(el) && (r.right > sw + 1 || r.width > sw + 1)) {
      report.offenders.push((el.id ? "#" + el.id : el.tagName.toLowerCase()) +
        " w=" + Math.round(r.width) + " right=" + Math.round(r.right) +
        " minW=" + getComputedStyle(el).minWidth);
    }
  });
  report.offenders = report.offenders.slice(0, 40);
  console.log(JSON.stringify(report, null, 2));
  return report;
})();
`FENCE`

実装案: `?debug=1` のときだけ次の各タイミングで診断を走らせ、結果をトーストとコンソールに出す: (1) 初期表示後、(2) 動画選択後、(3) **ファイル選択モーダル表示中**（`.sheet-foot` はモーダル内にしか無い）、(4) **再エンコード選択中**（クロップ層が載る状態）。常設するかは実装時に判断（既定は非表示）。

## 5. 修正方針（ポリシー）（v0.2 更新）

- **P1**: 折り返しは `overflow-wrap: anywhere`（`break-word` は使わない。`word-break: break-all` は CJK 以外にも有効）。
- **P2**: flex/grid のアイテムは `min-width: 0`（**フォーム部品・置換要素を含む**）。トラックは `minmax(0, 1fr)`。
- **P3**: 置換要素（video/img）は `max-width: 100%` + `min-width: 0`。
- **P4**: 1行省略は「`nowrap` + `overflow: hidden` + `text-overflow: ellipsis` + `min-width: 0`」の4点セット。
- **P5**: 溢れが想定される部分（ログ・フレーム一覧）は `overflow: auto` のスクロールコンテナに閉じ込める。
- **P6**: `100vw` は使わない。最終防波堤に `overflow-x: clip`（`hidden` ではなく）。
- **P7**: viewport meta から `user-scalable=no` / `maximum-scale=1.0` を外す（a11y）。ただし実機の倍率挙動が変わるため、診断で前後を比較する。

## 6. 修正一覧（実装順）（v0.2 更新）

1. 診断（`?debug=1`）を実装し、**実機で溢れ要素を確定**（4K ソースの動画を選択した状態で実行）
2. `.viewer video{max-width:100%;min-width:0}`、`.stage` と `.viewer` のトラックを `minmax(0,1fr)` に
3. `.inp, select.inp` に `min-width:0`。`.time-inp`（`.inp` クラスではない）も同様に `min-width:0`。`.crop-grid` / `.opt-grid` / `.inout` / `.kv` を `minmax(0,1fr)` に。`.crop-grid` は 480px 以下で2列
4. `.sheet-foot` に `flex-wrap:wrap`、その input を `flex:1 1 120px; min-width:0` に
5. `.src-sub span` に `min-width:0; overflow:hidden; text-overflow:ellipsis`
6. `#srcDetail` に `overflow-wrap: anywhere`
7. `.chip .nm` を `max-width: min(56vw, 100%)` に
8. `.badge` / `.tbtn` / `.entry .sz` / `.srcbar .btn` に `min-width:0`
9. web 版にも同ポリシーを適用（`.stage` 相当・`.meta-details`・`.file-list` を点検）
10. viewport meta の整理（`user-scalable=no` / `maximum-scale=1.0` の削除）
11. `html, body` の `overflow-x: hidden` を `clip` へ変更を検討

## 7. 受入基準（Acceptance Criteria）（v0.2 更新）

対象 UI: **Qwen 版と web 版の両方**。検証は **360px 幅相当**（DevTools 端末エミュレーション）と**実機スマホ**の両方で行う。ソースは**4K 動画（実ファイル）**を必須とし、加えて次を選択:

- 120文字の日本語ファイル名
- 120文字の**改行位置のない英数字・記号**のファイル名（Flash レビュー提案）

合格条件:

1. `document.documentElement.clientWidth <= window.screen.width + 1`（ICB が広がっていない）
2. `document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`（横スクロールなし）
3. `window.visualViewport.scale` が 1 のまま（倍率が変わらない）
4. §4 の診断で **スクロールコンテナ外**の `offenders` が 0 件（**通常状態とファイル選択モーダル表示中の両方**で確認）（`.frame-strip` / `.logbox` の子孫は押し広げに寄与しないため対象外。コンテナ内は参考値として記録）

## 8. テスト計画

- **静的**: `tests/check_ui_static.py` に追加 — `.inp` に `min-width:0` / グリッドが `minmax(0,1fr)` / `.viewer video` に `max-width:100%` / `.src-sub span` に min-width+ellipsis / `#srcDetail` に anywhere / `break-word` を単独で使っていない（実装時に `#toast` の `word-break:break-word` を削除し `overflow-wrap:anywhere` に一本化する。既存の `.job-sub` の `break-all` は min-content を下げるため許容） / `.sheet-foot` に flex-wrap。
- **動的（実機）**: §4 の診断を4タイミング（初期表示後・動画選択後・ファイル選択モーダル表示中・再エンコード選択中）で実行し、**通常状態とモーダル表示中の両方**で `icbExpanded=false`・`scale=1`・`offenders=0` を記録（スクリーンショット）。
- **回帰**: `test_unit` / `e2e_*` / `check_ui_static` 全通し。
- **将来**: ブラウザ自動化（Playwright）が入れば 360px ビューポートで 1〜4 を assert する。

## 9. レビューと完了条件

- 計画・成果物とも「DSH 経由 NVIDIA NIM GLM5.3」と「Agy Gemini 3.8 Flash」の**両方が完全Go**になるまで反復する。
- 実機最終確認はユーザー（モバイル）で実施。

## 10. リスク・ロールバック（v0.2 修正）

- リスク: `min-width:0` 追加で入力欄が必要以上に狭くなる / `.viewer video` の `max-width` で表示が変わる → 目視確認し、狭すぎる場合は `flex-basis` や列数を調整。
- リスク: viewport meta 変更でユーザーのピンチズーム挙動が変わる（a11y 改善だが体感が変わる）。
- ロールバック: 変更は CSS と meta のみ。作業前に `web-qwen/index.html` / `web/index.html` / `web/style.css` を退避（`.bak`）してから着手する。

## 11. 作業順序と見積り

1. 診断の実装と実機確認（0.5h）
2. CSS 修正（Qwen 0.5h / web 0.5h）
3. 静的テスト追加（0.5h）
4. 回帰 + レビュー 2 巡（1.5h）
5. ユーザーの実機受入（任意）

## 12. 未確定事項（実機で確認する）

- `initial-scale/maximum-scale` 明示時に、この症状が「自動縮小」なのか「ICB 拡張による相対的な小ささ」なのか。§4 の診断で `icbExpanded` と `visualScale` を記録して判定する。
- 4K 動画選択の前後で `.viewer` の幅がどう変わるか（M2 の検証）。

---
改訂: v0.3 で第30ラウンドのレビュー指摘（診断のスクロールコンテナ除外・.time-inp の min-width・break-word 検査の明確化）を反映。

付記: 調査は Gemini 3.8 Flash（agy CLI, --model gemini-3.8-flash-high, Web検索ツール使用）が実施し、上記 3 件の出典を引用。計画レビュー（第29ラウンド）で GLM から M1/M2/m1/m2/m3、Flash から英数字ケースの提案を受け、v0.2 で反映した。実装は未着手。
