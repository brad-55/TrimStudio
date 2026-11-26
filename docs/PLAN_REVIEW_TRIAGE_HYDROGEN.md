# Gemini 4 Hydrogen 外部レビュー Critical 指摘への対応計画（v1）

## 目的

2026-11-13 に agy 経由 Gemini 4 Hydrogen (xhigh) で実施したアプリ/ドキュメント外部レビューの
**Critical 指摘を事実確認し、修正・検証・再発防止テストまで行う**。
アプリの Major 指摘は今回のスコープ外とし、対応一覧をバックログとして明記する（次ラウンド）。

## レビュー結果のトリアージ

- アプリ: 却下（Critical 3 / Major 5 / Minor 2）。Critical 3 件はコードで再現確認済み。
- ドキュメント: 却下（Critical 3 / Major 6 / Minor 3）。Critical 3 件は実ファイル/実装で整合確認済み。

## アプリ修正（Critical）

### A1. プレビューとエクスポートで `addedStartMs` の解釈が不一致

- 事実: 設計（`docs/PLAN_AUDIO.md` L50/L212, `PLAN_AUDIO_EXPORT.md` L39/L103）では
  `addedStartMs` は**追加ファイル内の開始位置**。書き出しは `_added_cut_args` でシークするが、
  プレビューは `added_place_s` を**タイムライン上の遅延**として加算し、入力をシークしない。
- 修正: `app/preview.py`
  - **フィルタ順（確定）**:
    追加チェーン = `atrim=start=<added_skip_s + max(0,-added_delay_s)>`（**atrim は PTS 基準の絶対時刻**。
    書き出しの `-ss` も絶対時刻なので、start_time≠0 でも同じ基準になる。atrim 前に PTS を
    正規化しない）→ `asetpts=PTS-STARTPTS`
    → （`added_delay_s>0` のときのみ）`adelay` → `aresample=48000` →
    `aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo`（aresample は input 側の
    レート差を吸収する保険。aformat だけでも可だが既存実装に合わせて残す）→
    `apad=whole_dur=duration_s` → `atrim=end=duration_s` → `asetpts=PTS-STARTPTS`。
    元チェーン = `<shift>` → `aresample=48000` →
    `aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo` →
    `apad=whole_dur=duration_s` → `atrim=end=duration_s` → `asetpts=PTS-STARTPTS`。
    どちらも **48kHz/fltp/stereo** で、かつ**ちょうど duration_s サンプル**に正規化してから amix。
    **負遅延（added_delay_s<0）は adelay を使わず**、`atrim=start=added_skip_s+|d|` で先頭を余分に
    カットして `asetpts=PTS-STARTPTS` する＝内容を前に詰める（これが負シフトの実現方法）。
    `adelay` に負値は決して渡さない。
  - 概念を2つに分離する:
    * `added_skip_s` = `addedStartMs/1000`（**追加ファイル内のスキップ量**。負値は API で 400
      `invalid_shift`。UI は `addedStartInp` の `min='0'` と `startMsVal()` で事前防止）
    * `added_delay_s` = `addedShiftMs/1000`（**タイムライン上の遅延量**）。
      **追加音源の `start_time` は加算しない**。ただし**書き出しの `-ss` が start_time をどう扱うかは
      実機パイロットで確定**し、プレビューの atrim 開始位置を書き出しと同じ切り出し位置に合わせる
      （不一致時は atrim start を補正。無音化はしない）。
      `adelay` は **書き出しと同一の `_mix_filter()` を呼び出して生成**する（同じ `int(round(sec*1000))`・
      `all=1`。片方だけ丸めを変えない）。
      丸め誤差の上限（0.5ms）を含む実測値を REVIEW.md に記録する。
      負値は負遅延として atrim 側で吸収する。
  - `_audio_filter(...)` に `added_skip_s` を追加し、**追加チェーン**に
    `atrim=start=<added_skip_s + max(0,-added_delay_s)>,asetpts=PTS-STARTPTS` を適用してから
    `adelay`（`added_delay_s>0` のときのみ）を適用する。
  - 上記の順序で**すべての入力チェーンを同じ長さに正規化**する。追加音声が空（skip が実長超過）なら
    無音が区間長分パディングされ、区間長より長ければ終端がトリムされる。
  - 正規化後の両入力はちょうど `duration_s` なので `amix=inputs=2:normalize=0:duration=first` で長さは
    `duration_s`。**入力順は「元 → 追加」**、normalize=0 の振幅合成は既存仕様のまま（limiter は追加しない）。
    最後の `apad=whole_dur=duration_s,atrim=end=duration_s,asetpts=PTS-STARTPTS` は**保険**。
  - **区間長 = プレビュー対象動画ソースの variant duration（`_run_build` の `duration_s`）** に固定。
    added のみ/bothTracks/bothMix でも同じ動画タイムライン長。テストで
    **プレビュー duration ≈ ソース duration** も断言する。
  - **実装前パイロット**:
    1. 「atrim で 0 サンプルになった追加チェーン」に aresample/aformat/apad を適用して
       無音が区間長分出るか実機確認する。
    2. `start_time ≠ 0` の追加音源で、**書き出しの `-ss` の実効切り出し位置**を実測し、
       プレビューの atrim 開始位置を同じ位置に合わせる（必要なら補正式を入れる）。
       `anullsrc` は start_time 不一致のために使わない。補正式・実測値は REVIEW.md に記録する。失敗する場合は
    `anullsrc=r=48000:cl=stereo,atrim=end=duration_s,asetpts=PTS-STARTPTS` の無音ソースへ差し替える
    フォールバックを実装してから本実装に進む（anullsrc は無限長のため必ず atrim で終端する）。
  - 変数名 `added_place_s` は廃止。
  - 無音は「追加チェーンが空 → 共通 apad が無音で埋める」ため、入力除外の事前分岐は行わない
    （実装が単純で、長さ既知/不明の差も吸収できる）。
- テスト: `tests/test_preview_filters.py` に atrim 期待を追加。**48kHz mono 正規化**の相関で比較する
  （受入条件と同じ条件）。**bothTracks / bothMix のプレビューはどちらも既存仕様どおり1トラックへ
  ミックス**（元+追加）。addedStartMs の解釈統一を added/bothTracks/bothMix の3モードで確認する。境界（addedStartMs=追加長、
  超過、長さ不明、負遅延との合計が長さ以上→無音）も追加。`tests/e2e_audio_export.py` に
  addedStartMs=1000 の**プレビュー/書き出し一致**検査を追加（プレビュー proxy 音声をデコードし、
  追加音源の 1.0s 以降との相関 **> 0.8**、0s 開始の期待との相関は**正位置より 0.2 以上低い**こと。
  なお将来フォールバック経路も含める場合は md5 ではなく相関比較に切り替える（本ラウンドはコピー固定）。
  （音声の負シフトは既存の 110ケース行列でプレビュー/書き出しとも検証済み。バックログの「負 -ss」は
   **映像キーフレームシーク**の話で音声シフトとは別。A1 の e2e は addedStartMs の正方向のみを対象とする。）
  **追加音源の `start_time` ≠ 0** のケース（例: `-output_ts_offset` で 0.2s 付与した m4a）を
  e2e に1件追加し、プレビュー/書き出しで同じ内容になることを確認する（パイロットで確定した
  切り出し位置に合わせる）。
  e2e は**元動画の音声を無音（anullsrc）**にした専用フィクスチャを使う（元音声とのミックスで相関が
  希釈されないようにする）。プレビュー proxy の音声仕様は既存実装の **AAC 128kbps・ソース音声
  サンプルレート（テストは 48kHz）** を前提とし、実測記録にも併記する。追加音源は**非周期のチャープ列**（例: `aevalsrc='0.6*sin(2*PI*(220+380*mod(t,0.37))*t)*exp(-8*mod(t,0.37))'`、
  0.37s 周期で 1.0s シフトが整数倍にならない）を生成する。相関は
  **±50ms のラグ探索後の最大値**で判定する（AAC 再エンコード/リサンプルの数ms遅延に頑健）。
  「1.0s ずらし」と「0s 開始」の**両方に同一の ±50ms ラグ探索**を適用し、**真位置の最大相関 − 誤位置の
  最大相関 >= 0.20（絶対差）** を**テストコード内の assert** で固定する。閾値はテストコード定数
  `CORR_MIN=0.80` / `CORR_DIFF_MIN=0.20`（変更ゲート。コメントで方針を明記）とし、実測記録には
  両側の最大相関値と**ピークレベル（クリッピング確認用）**も残す。ピークが 0dBFS を超える場合は
  REVIEW.md に既知問題として記録し、limiter 等の対策は次ラウンド検討とする（本ラウンドでは仕様変更しない）。
  閾値を変更する場合は REVIEW.md に実測値とともに「受入条件の変更」として記録する。
  ラグ探索幅は **±50ms のまま固定**（チャープ周期 0.37s より十分小さく、周期の整数倍探索を避ける）。
  **実装初期（テストコード作成直後）に実測値を確認し、閾値の妥当性を docs/REVIEW.md に記録してから
  本実装の受入判定に使う**（実測が閾値未満なら音源/閾値を見直す）。

### A2. UI の追加音声ずらし方向ヒントが逆符号

- 修正: `web-qwen/index.html` の追加音声ヒントを「プラスで遅く、マイナスで速くなります。」に修正。
- テスト: 旧文言の非存在＋新文言の存在を静的ガードに追加。

### A3. 再エンコードモードで追加音声が黙殺される

- 方針: 現状の再エンコード経路は追加音声を出力できないため、**API で明示的に 400 拒否**し、
  UI でも再エンコード選択時に追加系モードを選べないようにする（無言の欠落出力を防止）。
- 修正:
  - `app/main.py`: `mode=reencode` かつ `audioMode in (added, bothTracks, bothMix)` のとき
    `400 invalid_request`「再エンコードでは追加音声を利用できません（無変換を選ぶか、音声モードを
    元のみ/消音にしてください）」。
  - `web-qwen/index.html`: **動画モードが reencode のとき**追加系（**added / bothTracks / bothMix の3種**）
    ラジオを disabled にし、**選択中が追加系の場合のみ**
    元のみへ戻してトースト通知（**消音はそのまま維持**）。**無変換へ戻しても追加系モードは復元せず
    「元のみ」のまま**とする（黙示的な復元はしない）。トースト文言は
    「再エンコードでは追加音声を使えません。音声モードを『元のみ』に戻しました。」に固定。
    **動画モードが reencode 以外のとき**は追加系ラジオの disabled を解除する（双方向制御）。
    再エンコード時の音声パネルには「再エンコードでは追加音声は利用できません（元のみ/消音が選べます）。」
    の理由ヒントを表示し、静的ガードで固定する。静的ガードでは **3 radio それぞれ**の disabled 条件を確認する。
- テスト: API 400 の E2E、DOM 挙動（再エンコード選択で追加系が無効化・元のみへ復帰）、静的ガード。
- **既存テスト監査**: `e2e_audio_matrix`, `e2e_audio_export`, API e2e に
  `mode=reencode` + added/bothTracks/bothMix のケースが無いことを確認し、あれば 400 期待へ更新する
  （監査結果を REVIEW.md に記録）。

## ドキュメント修正（Critical）

### D1. タイムライン（シークバー）説明の陳腐化・自己矛盾

- 実装（`web-qwen/index.html`）に合わせて README 日英を書き換える:
  - バーは PC 96px / モバイル 88px。以下の数値は**実装 CSS/JS から抽出**した確定値で、README 記述と
    静的ガードを一致させる。**計画内の行番号は根拠提示のみ**とし、README・静的ガードには
    セレクタ/数値のみを記録する（行番号は変更で陳腐化するため成果物には含めない）。
  - **上側**＝白い丸型 `▶` の再生位置ハンドル（28px、top 9px）。
  - **下側**＝赤い `IN` ボックスとオレンジの `OUT` ボックス（34x26、bottom 10px）。
  - キーフレームは**白い半透明の縦線**（黄色ではない）。
  - 当たり判定は左右 48px、ドラッグは 3px 超で開始、IN/OUT は交差しない、バー全体タップでは
    シークしない、2段境界はバー高さの約46%。
  - 「上段＝IN/OUT、下段＝再生位置」の逆転記述を削除。
- 履歴文書: `docs/PLAN_TIMELINE.md` 冒頭に「本計画は当時の記録。現行UIは README/実装を参照」と
  ステータス注記。`docs/REVIEW.md` の第46ラウンド節に「その後 96px/88px・ボックス型ハンドルへ
  刷新済み」の注記を追加（履歴は改変しない）。

### D2. 音声タイミングの「全経路無変換」虚偽記載と符号不整合

- README 日英の音声節を経路別に正確化:
  - original / added / bothTracks: パケットコピーが基本。ただし
    (a) 正シフトで先頭に遡る余裕がない場合は**既定で音声のみ再エンコード**、
    (b) `delayNoReencode` ON かつ ELST 対応コンテナのみ**無変換のコンテナ開始位置**、
    (c) `addedReencode` ON は追加音声を再エンコード。
  - **映像の再エンコード（mode=reencode）では追加音声（added/bothTracks/bothMix）は利用不可**
    （元のみ/消音のみ。API は 400 invalid_request で拒否）。なお (a) の「音声のみ再エンコード」は
    mode=lossless 内のフォールバックの話で、mode=reencode とは別である旨を README に補足する。
  - bothMix は常に音声再エンコード。mute は音声なし。
  - 追加音声: `+`＝遅らせる、`-`＝進める。`addedStartMs` は**追加ファイル内の開始位置**。
- `docs/TEST_DESIGN.md` の音声網羅表（既定 adelay 再エンコードのみ記載）を
  「既定」と「delayNoReencode=true (elst 無変換)」の2系統へ更新。
- 英語版 README も同期。

### D3. `docs/API.md` の大規模陳腐化

- `app/main.py` の実ルート（39本）を正として API.md を再構成:
  - 欠落エンドポイントを追加: POST /api/media-dates, POST /api/fs/delete, GET /api/fs/zip,
    POST /api/audio/sync, POST /api/preview/build, GET /api/preview/media/{key},
    POST /api/luts/dir, POST /api/luts/reveal, POST /api/luts/upload, GET /compare, 静的マウント。
  - GET /api/config の実応答、/api/health の build/ffmpegPath、/api/token の strongMode 分岐、
    /api/browse の引数/応答（mtimeMs/ctimeMs/total/offset/limit/truncated）、
    /api/fs/copy・move の sources 配列、/api/sources 系の preview 付帯情報、
    /api/exports の delayNoReencode・audio result サブオブジェクト、
    ジョブ kind（export/proxy/sprite/index/copy/move/preview）を実装に合わせる。
  - エラーコード/型/構造（mkdir_failed の位置、認証免除、Host 許可）を修正。
  - `mode=reencode` と追加音声系 `audioMode` の排他（400 invalid_request）を、**実際の応答文言そのまま**で明記。
    API 400 文言は「再エンコードでは追加音声を利用できません（無変換を選ぶか、音声モードを元のみ/消音にしてください）」。
    UI トーストは「再エンコードでは追加音声を使えません。音声モードを『元のみ』に戻しました。」（別文面で可、
    それぞれを静的/E2E で固定）。
- 再発防止: `tests/check_api_docs.py` を追加し、**AST で `@app.<method>("<path>")` デコレータだけ**を抽出して
  API.md と突合する（`app.mount(...)` の静的マウントはデコレータではないため自動的に対象外）。
  正規化規則: **位置を保ったセグメント単位の比較**（`{param}` は任意の1セグメントに一致する
  ワイルドカード。セグメント数/位置は保持）、末尾スラッシュ無視、
  クエリ（`?...`）除去、比較は「METHOD + 正規化パス」。**同一 METHOD+構造でパラメータ名だけ異なる
  ルートが存在しないことは確認済み**（存在したら警告）。現行39ルートはすべて `@app.<method>`
  デコレータ登録であることも確認済み（`add_api_route` 等の非デコレータ登録は無し）。
  さらに**抽出ルート数が定数 `EXPECTED_ROUTE_COUNT=39` と一致しない場合 FAIL** とする。
  FAIL 時は「抽出数 / API.md 記載数 / 期待数」を表示し、「ルート追加時は EXPECTED_ROUTE_COUNT と
  API.md の該当セクションを更新」と案内する。定数は**意図的なルート変更ゲート**であり、テストコードのコメントにもその旨を明記する。
  既存テストスイートに組み込む。

### D4. 付随する整合修正（Critical の解消に必要な範囲）

- バージョン表記: DELIVERY.md を「v0.1.0 時点の記録」と明記（バージョン更新とリリースは「バージョン」節に集約）。
- README のテスト件数・現行機能（折りたたみ UI、実メディア行列 110 ケース）を現状へ更新。
- 英語 README の該当節を日本語版と同期。

## 既知問題の明示

- 今回スコープ外のアプリ Major / ドキュメント Major は、リリースノートと DELIVERY.md に
  「既知の未対応指摘（次ラウンド対応）」として一覧を記載する。

## テスト・合格条件

- 新規/更新: `test_preview_filters.py`（atrim）、`e2e_audio_export.py`（addedStart プレビュー一致）、
  `e2e_audio_api.py` または新規（再エンコード+追加の 400）、`test_audio_ui_behaviour.js`
  （再エンコード選択時の無効化/復帰）、`check_ui_static.py`（ヒント/文言/UI制限）、
  `check_api_docs.py`（ルート網羅）。
- 既存回帰: unit、静的ガード、settings/timeline/smoke、e2e_audio_export、e2e_audio_matrix（110ケース）、
  e2e_preview_api、e2e_preview_sync。
- 受入:
  1. **ずらし0（addedShiftMs=0 / audioShiftMs=0）・ELST 対応 mp4** の addedStartMs=1000 ケースで、
     **書き出し**は、出力の追加音声ストリーム全体（先頭から）を ADTS 再フレームした md5 が、
     ソースの追加音源を `-ss (addedStart + max(0,-addedShift))` 相当で切り出したパケット列の md5 と
     一致すること（既存 `packet_md5` と同じ出力側シーク規則）。コピー経路であることを
     `result.lossless==true`・`result.audioReencoded==false`・`audio.delayMode=="none"` でも断言する
     （再エンコードフォールバックが起きていないことを直接確認）、
     **プレビュー**は 48kHz mono に正規化した相関（> 0.8）で追加音源の 1.0s 以降と一致する
     （プレビューは再エンコードされるため md5 は書き出しのみ。プレビューと書き出しのバイト一致は求めない）。
  2. UI ヒントが符号と一致し、静的ガードで固定。
  3. 再エンコード+追加系が API 400 / UI 選択不可で、無言欠落しない。
  4. README 日英のタイムライン・音声説明が実装と一致し、旧文言が残らない。
  5. API.md が全ルートを網羅し、自動突合テストが通る。
  6. 上記を含む全テストが FAIL 0。
- バージョン: **0.3.3 に更新**（現行 0.3.2 からの次版。既存タグ v0.3.3 は無いことを確認済み）し、リリース v0.3.3 を作成。
- **手順**: 全テスト FAIL 0 確定 → README/docs の件数・既知問題を確定 → version 0.3.3 へ更新 →
  コミット/push → タグ v0.3.3 → リリース v0.3.3 作成 → 本番再起動。README のテスト件数は
  この手順で最終値へ更新し、docs/REVIEW.md の記載と一致させる。
  陳腐化防止のため、README には「詳細な件数は docs/REVIEW.md を参照」も併記する。

## スコープ外（バックログ、次ラウンド）

- アプリ Major: 出力尺と -t、_mux_args の itsoffset、負 -ss、bothMix フォールバック、NO_ELST/mxf、
  audio-only 正シフト拒否、並列予約/SSE、Tailscale/Host 検証、fs copy/move 検証、既定 denyRoots、
  options 非dict、ZIP/DB リーク、elst パーサ、長パス、全編同期デコード、イベント欠落。
- ドキュメント Major: ファイル名例のタイムスタンプ、エクスプローラ説明、設定/初期導入ガイド、
  英語 README の見出し構造、テスト件数以外の運用文書陳腐化。
