# レビュー記録（Trim）

## 計画レビュー

| ラウンド | 版 | レビュアー1: DSH/NIM z-ai/glm-5.3-flash (max) | レビュアー2: Agy gemini-4-argon-high |
|---|---|---|---|
| 1 | v0.1 | 条件付きGo（Major 4 / Minor 13） | 条件付きGo（Critical 2 / Major 6 / Minor 2） |
| 2 | v0.2 | 条件付きGo（Major 1 / Minor 9） | 完全Go（Minor 3） |
| 3 | v0.3 | 完全Go（Minor 7） | 完全Go（Minor 1） |

結論: v0.3 で 2 名の完全Go を取得。条件付きGo のまま進めない方針に従い、ラウンドごとに全指摘を反映した。

## モデル代替（ユーザー承認済み）

- 元指定 z-ai/glm-5.3 は NIM で 2026-10-28 EOL、moonshotai/kimi-k3 は 2026-10-15 EOL。
- レビュアー1 を z-ai/glm-5.3-flash に、予備を nvidia/nemotron-3-ultra-550b-a55b に変更（承認済み）。
- UI は本人実装とローカル Qwen（127.0.0.1:8080, qwen3.8-flash-next-iq3_s）実装の二重とし、ユーザーが採用。

## キャッシュヒット方式（要件 10）

- 共通レビュー仕様（REVIEW_SPEC.md）を不変の接頭辞とし、可変部を末尾に置く。
- DSH は SDK JSON-RPC の常駐デーモン（daemon_dsh.py）が 1 セッションで複数レビューを処理。
- Agy は --continue で同一会話を再開。
- 証跡: GLM の usage は inputTokens 13698 / outputTokens 20904（初回）。

## v0.3 に対する残存 Minor（完全Go、実装時に反映）

GLM:
1. inSnap=next の二義性 → API はエラーとし、UI が prev 適用案を提示して再送信する方式に確定。
2. 索引対象は v:0 固定ではなく、選択された映像ストリームをキーに保持。
3. 第2ラウンド Agy 指摘の対応記録 → 本表に追記（デュアルスタック、A/V 同期、ffprobe 引数）。
4. /media 行の重複 → ?variant= の 1 行に統合。
5. 節順序（3.6 が 3.5 より前）→ 実装時に docs/API.md で整理。
6. アクティブソースの定義 → 再生中・ジョブ実行中・直近 10 分アクセスを退避対象外。
7. requireToken の意味 → CSRF トークンは常時要求に固定し、フラグは strongMode のみ。

Agy:
1. 体裁（節番号順序・/media 重複）→ 上記と同じ。

## 成果物レビュー

実装後に同一レビュアーで実施し、完全Go を取得する（未実施）。
## 成果物レビュー

| ラウンド | レビュアー2: Agy gemini-4-argon-high | レビュアー1: DSH/NIM z-ai/glm-5.3-flash (max) |
|---|---|---|
| 1 | 条件付きGo（Critical 3 / Major 4 / Minor 1） | デーモンのタイムアウトで取得失敗（再実行） |
| 2 | 条件付きGo（Major 3 / Minor 2） | デーモンのタイムアウトで取得失敗（再実行） |
| 3 | 完全Go（Minor 1・任意） | レビュー実行中 |

### 第1〜2ラウンドで修正した主な内容
- 無変換カットの方式を、映像（開始キーフレームに着地させる中間シーク）と音声・字幕（開始時刻で切り出し）を分離し、-itsoffset で 0 起点に揃えて mux する 3 パス方式に変更し、A/V 同期と尺を一致させた。
- ストリーム互換判定による非互換ストリームの除外と警告、webm 維持、faststart のコンテナ限定、音声 copy 不可時の AAC 再エンコード。
- LUT の luts ディレクトリ限定と拡張子保持、16bit 中間、色メタデータ既定 bt709、クロップの偶数丸めとクランプ、フィルタ順 options.order。
- 同一オリジン検証、strongMode の Cookie 認証、アップロードの空き容量・拡張子検証、Host 解決の自ホスト限定。
- paths/validate の 500 解消、240 文字パス対応、LRU の空き容量考慮と実行中ジョブ除外、スプライト削除、ジョブの SQLite 永続化、Windows プロセスツリー終了。
- 出力先にディレクトリを指定した場合のファイル名生成と validate_output のディレクトリ対応。
- 両 UI で実カット区間と差分を常時表示、Qwen 版のスナップ選択を無変換モードでも操作可能に配置、strongMode のトークン入力導線。

### 第3ラウンドの残存 Minor（任意）
- 3 パス無変換カットでキャンセル・異常終了した場合に .v / .a 一時ファイルが残り得るため、finally でも削除するのが望ましい（機能への影響なし）。

## 成果物レビュー結論（第4ラウンド）

- レビュアー1（DSH/NIM z-ai/glm-5.3-flash, reasoning effort max）: **完全Go**
- レビュアー2（Agy gemini-4-argon-high / 第5ラウンド以降はクオータ枯渇のため gemini-3.8-flash-high に差替）: **完全Go**
- inSnap=next の扱いは「実装は prev へ自動フォールバックし、結果に fallback=true と警告を含める」で確定。
- 残存する運用項目（コード判定を左右しない）: モバイル実機での受入 A3、数十 GB 動画での索引・性能検証、非互換ストリーム/異常系の一部 E2E、チャプター時刻補正、コンテナ選択 UI、requirements のピン留め。

## 追加要件とレビュー（第5〜7ラウンド）

ユーザー追加要望（音声ファイルのトリミング対応、Qwen版の前回フォルダ記憶と音声再エンコード既定オフ、書き出しエラーの明確化）に対して、成果物レビューを第5〜7ラウンド実施した。

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 5 | 条件付きGo（Major 2: aif/aiff アップロード、UI の accept） | 条件付きGo（同一の Major 2） |
| 6 | 条件付きGo（Major 1: Matroska 互換表と映像なし経路） | **完全Go** |
| 7 | **完全Go** | **完全Go** |

- レビュアー2 は Gemini 4 Argon のクオータ枯渇（HTTP 429）のため、ユーザー指示により gemini-3.8-flash-high へ差替えた。
- 第7ラウンドの Flash 判定は、ターン上限で全ファイル探索が完走しなかったため、差分要約と実測エビデンスに基づく判定（完全Go）である。第6ラウンドでは同一モデルが全ファイルを実読して完全Goを返しており、第7ラウンドの差分はその指摘への対応のみ。
- 第7ラウンド GLM の残存 Minor（asf 音声出力の拡張子、出力検証基準、README のテスト一覧、wmv の MKV 退避の明記）は反映済み。残タスクはモバイル実機の受入確認と数十GB級の性能検証のみ。

## 追加改善とレビュー（第8〜9ラウンド）

計画に残っていた項目と繰り返し指摘されていた Minor を解消した。

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 8 | **完全Go** | 判定未取得（ターン上限で出力が途中終了） |
| 9 | **完全Go** | **完全Go** |

第8〜9ラウンドで実装したもの:
- 出力コンテナの明示指定（計画 §3.2）。API は許可値12種のホワイトリスト、非互換・未知値・単一音声コンテナへの複数指定はジョブを作らず 400 invalid_container。両 UI に選択を追加。
- 出力先に残った未完了 .part（1時間以上前、名前に .part と .trim- を含むもの）を書き出し開始時に自動削除。安全のため data/work の起動時掃除は従来どおり。
- requirements.txt を実測バージョンに固定（fastapi 0.162.0 / uvicorn[standard] 0.54.0 / python-multipart 0.0.33）。
- tests/e2e_abnormal.py を追加（音声なし・複数音声・VFR・非 ASCII 深いパス・コンテナ指定と 400・古い .part の削除・破損ファイル 400）。合否集計と RESULT/exit code 付き。
- 索引性能の実測: 5041.7MB・4K HEVC 10bit・9分54秒でキーフレーム594件を 1.0 秒（計画 §13 の5分目標に対して十分）。

第9ラウンド GLM の Minor（e2e_abnormal の合否集計）は反映済み。残るのはモバイル実機での受入確認（計画 M7・A3）のみ。

## 追加機能とレビュー（第10〜16ラウンド）

ユーザー追加要望（メタデータのビットレート表示と詳細表示、再エンコードのビットレート指定、出力先エクスプローラ）に対応し、あわせて各ラウンドの残存 Minor を解消した。

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 10 | 条件付きGo（Major 1: 音声のみ再エンコードのビットレート踏襲漏れ） | 完全Go |
| 11 | 条件付きGo（Major 1: mkdir のドット入り名切り詰め） | 完全Go |
| 12 | 完全Go | 完全Go |
| 13 | 完全Go | 完全Go（要点確認） |
| 14 | 完全Go | 完全Go |
| 15 | 完全Go | 完全Go |
| 16 | 完全Go | 完全Go |

第10〜16ラウンドで実装・修正したもの:
- メタデータ拡張: format/stream の bit_rate（無ければ size*8/duration）、profile/level、色情報、channel_layout、nb_frames、タグ。sources に meta_json を追加し既存行は開き直しで自動再取得（索引維持）。API は bitRate/videoBitRate/audioBitRate/meta/streams 詳細を返す。
- メタデータ表示: 両 UI で主要項目を常時表示し、全ストリームとタグを折りたたみで表示。ビットレートは 1Mbps 以上を Mbps 表記。
- 再エンコードのビットレート指定: options.videoBitrate/audioBitrate（kbps）。映像は未指定なら CRF、音声は未指定なら元の音声ビットレートを踏襲（映像あり・音声のみの両経路で実測）。不正値は 400。コンテナ別の再エンコード音声コーデック表を導入し、2ch 制約（wmav2/libmp3lame/mp2）は 400 で事前拒否。
- 出力先エクスプローラ: 両 UI に参照ボタンとフォルダ選択モーダル、新規フォルダ作成（POST /api/fs/mkdir）。ディレクトリ名は専用サニタイズ（ドット入り名を保持、予約名は _ 前置、空名は 400）。
- ジョブ履歴: error 列を追加して永続化し、再起動後も /api/jobs/{id} と /api/jobs?history= で参照可能。起動時に queued/running の残骸を interrupted by restart として整合。両 UI のポーリングは連続5回失敗で打ち切り。
- その他: 不正 JSON / 非オブジェクトボディ / startUs・endUs 非整数 / 不正ビットレートを全 POST で 400 に統一。入力検証、mkdir の封じ込め、Host 検査の厳格化（DNS 解決廃止）を維持。

残る未実施（ユーザー受け入れ項目）: モバイル実機での受入確認（計画 M7・A3）と、採用 UI 決定後の UI E2E 自動化。

## 機材固有拡張子と衝突回避（第18〜19ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 18 | 条件付きGo（Major 1: 非PCM音声の .mxf が失敗） | 完全Go |
| 19 | **完全Go** | **完全Go** |

- 機材固有拡張子を計40種に拡張（Insta360/GoPro の .lrv、Insta360 .insv/.insp、GoPro 360 .360、業務機 .mxf、DV .dv、DVD .vob、RealMedia .rm/.rmvb、Flash .f4v、.3g2、.mod/.tod、.m2t など）。出力コンテナは自動決定（MP4/FLV/MXF/AVI/MPEG-PS/MKV）。XAVC 相当（H.264+AAC の .mxf）は MXF 非対応のため MKV に自動退避。MXF は実互換表（mpeg2/h264/dv 映像、48kHz PCM のみ）で判定。
- ファイル名衝突の自動回避: 出力ファイルは既存と被れば -1, -2 … と連番（全経路で適用、上書きなし）。ソース表示名も同名なら連番化（DB ロックで競合解消）。
- e2e_extensions.py で13ケース+XAVC退避を検証。

## 操作性の改善（第20ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 20 | **完全Go** | **完全Go** |

- 応答待ちスピナー（両 UI、参照カウンタ＋0.2秒遅延表示、finally で必ず解除）。
- ジョブ一覧の刷新（種類・状態・進捗・ソース名・「N 実行中 / N 待機中 / 計 N」）。/api/jobs に sourceName を追加。
- エクスプローラのコピー/移動（app/fsops.py。ジョブ実行・進捗・停止可、.part 経由の原子的置換、衝突時は -1 連番、同一ボリュームは rename、跨ボリュームはコピー後削除、キャンセル時は中途の出力を破棄）。POST /api/fs/copy・/api/fs/move。同一フォルダへの移動やフォルダ自身へのコピーは事前検証で 400。
- Qwen UI: メタデータ詳細を全幅配置（「PC から選択」との重なり解消）、エクスプローラの内側スクロール＋背景スクロール抑止、ドライブ切替セレクト追加、装飾アイコンの明示。
- 第20ラウンド後にレビュアー指摘の 3 Minor（新 API の文書化、事前検証への繰り上げ、跨ボリューム移動の後片付け）も反映済み。
## 応答待ちで操作不能になる不具合の修正（第21ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 21 | **完全Go** | **完全Go** |

- 原因: 応答待ちオーバーレイの CSS display:flex が hidden 属性（UA スタイルの [hidden]{display:none}）に優先し、起動直後から全画面を塞いでいた。
- 修正: 両 UI に [hidden]{display:none!important} を追加（#reencode-options など同種の潜在不具合も同時に解消）。API を AbortController でタイムアウト（既定60秒 / アップロード30分 / キーフレーム180秒）、25秒で「応答がありません — 操作を再開」ボタンを表示し手動解除も可能に。
- 再発防止: tests/check_ui_static.py（26項目）で両 UI のガード・初期 hidden・解除ボタン・タイムアウト定数を静検証。
## Qwen UI の一覧まわりと待機表示（第22ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 22 | **完全Go** | **完全Go** |

- Qwen エクスプローラを2行グリッドに変更（1行目=アイコン+名前+サイズ、2行目=コピー/移動）し、名前の表示領域を確保。超長名は中間省略（先頭60%+…+末尾40%）＋title に全文。
- 長名でのレイアウト崩れ対策（チップの max-width/ellipsis、ソース名の max-width、ボタンの flex 固定、overflow-wrap）。
- 履歴一覧の整理: Qwen は直近6件＋「他 N 件を表示」＋✕削除（確認付き）、web は直近8件＋同様の✕削除。PC 上の元ファイルは残る。
- 待機表示の再武装を排除: 背景ポーリング（ジョブ一覧・ジョブ照会・キーフレーム）を silent 化し、解除後はユーザー操作があるまで待機状態にならない。Qwen の silent が効かないバグも修正。
- tests/check_ui_static.py を38項目に拡張。
## 出力先指定後にスクロール不能になる不具合（第23ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 23 | **完全Go（指摘なし）** | **完全Go** |

- 原因: Qwen 版でファイル選択モーダルを開く際に背景スクロールをロックする no-scroll を付けていたが、「このフォルダを使う」で出力先を決定する経路だけ閉じる際に解除していなかった。
- 修正: モーダルを閉じる処理を hideBrowse() に一本化し、全経路（出力先決定・コピー/移動・閉じる・ファイルを開く）で必ずロックを解除。加えて body:has(.modal.show){overflow:hidden} を併用し、クラスが残ってもページが固まらない二重の安全策とした。
- 再発防止: check_ui_static.py に「解除は1箇所のみ」「生の show 解除は hideBrowse 内のみ」等 5 項目を追加。
## 可読ファイル名・OUTサムネイル・レイアウト安定化（第24〜25ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 24 | 条件付きGo（Major 1: 新命名で .part 掃除が無効化） | 完全Go |
| 25 | **完全Go** | **完全Go** |

- 出力名を「元名_切出<開始>-<終了>_<モードと指定内容>.<拡張子>」に変更（例: IMG_1234_切出1m30s-1m35s_再エンコード_H265_1500kbps_手ブレ補正_切抜320x180.mp4）。指定の無い項目は付与せず、時間は 0s / 1m05s / 1h02m03s 形式。
- Qwen の OUT サムネイル: 要求時刻を最終フレーム（duration − 1フレーム）にクランプし、読み込み直後とメタデータ取得後にも再取得。失敗時はプレースホルダ表示。
- Qwen のソースバーをグリッド化し、ファイル名の長さでページレイアウトが変わらないようにした。
- 第24ラウンド Major: 命名変更で .part の自動掃除フィルタが一致しなくなっていたため、旧形式 .trim- と新形式 _切出 の両方を対象に修正（無関係な .part は保持）。
- 第25ラウンド Minor: 到達不能だった短縮分岐を削除し、sanitize_name の80文字キャップと _fit_length の二段構えであることをテストで明示。
## クロップUIと横溢れの修正（第26ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 26 | **完全Go（指摘なし）** | **完全Go** |

- クロップをプレビュー上の枠で調整できるようにした（Qwen UI）。ドラッグで移動、四隅・辺のつまみでリサイズ（Pointer Events、タッチ対応、偶数化、元動画範囲にクランプ）、全体/16:9/9:16/1:1/4:3 プリセット、数値入力と双方向同期、全体のときは crop を送らない。letterbox を考慮した座標変換。
- 長いファイル名でページが横に広がり「表示倍率が変わったように」見える不具合の原因は、通知トーストが折り返さず、非表示後も DOM に残って恒久的にはみ出していたこと。トースト/エラー欄に折り返しを追加し、両 UI に html,body の overflow-x ガードを追加。
- check_ui_static.py を62項目に拡張。
## ダウンロード機能とプロキシ説明の修正（第27〜28ラウンド）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 27 | 条件付きGo（Major 1: ダウンロードが拡張子無制限で LAN から任意ファイルを取得可能） | 完全Go |
| 28 | **完全Go（指摘なし）** | **完全Go** |

- GET /api/fs/download?path= を追加。MEDIA_EXTS（動画・音声）以外は存在有無を漏らさず 400、許可ルート内の既存メディアファイルのみを Content-Disposition: attachment で配信（日本語名は filename*）。
- 書き出し完了の結果欄・ジョブ一覧・エクスプローラの各行（両 UI）にダウンロード導線を追加。
- プロキシの説明文を状態別（未生成／プロキシ再生中／元の画質再生中）にし、いずれも「書き出しは無変換」を明記。ボタンは「元の画質で再生」⇔「プロキシで再生」のトグルに変更（再生成しない）。
- e2e_download.py（11項目）、check_ui_static.py（71項目）。
## 表示倍率（レイアウト）問題の計画レビュー（第29〜32ラウンド・実装前）

| ラウンド | レビュアー1: DSH/NIM glm-5.3-flash (max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 29（計画 v0.1） | 条件付きGo（Major 2: 診断基準が ICB 拡張で空虚／.viewer video と .sheet-foot の欠落） | 完全Go |
| 30（計画 v0.2） | 条件付きGo（Major 1: スクロールコンテナ子孫の誤検出） | 完全Go |
| 31（計画 v0.3） | 条件付きGo（Major 1: body をクリップ祖先に含めると全要素除外で空虚） | 完全Go |
| 32（計画 v0.4） | **完全Go** | **完全Go** |

- 調査は Gemini 3.8 Flash（agy CLI、Web検索ツール）が実施し、MDN overflow-wrap / MDN viewport meta / web.dev RWD basics の3件を引用。
- 計画: docs/PLAN_LAYOUT.md。原因候補の最優先は置換要素の固有幅（4K video）と、フォーム部品を含む 1fr グリッドの min-width:auto。
- 実装は未着手（計画の完全Goをもって次段階へ）。

## TrimStudio 採用 UI と要望6件（第33〜34ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 33 | 却下（Critical 1: 設定 JS が <style> 内に混入し起動時 ReferenceError／Minor 2） | 完全Go |
| 34 | **完全Go**（Critical 解消を確認。残りは Minor/Info のみ） | **完全Go** |

- 第33ラウンドの Critical は挿入アンカーが CSS のセクションコメントと同名だったことが原因。JS ブロックを <script>（boot() 直前）へ移動し、構造ガード（<style> 内に JS が無い／主要関数が <script> 内）とランタイム・スモーク（tests/smoke_qwen_js.js、ネガティブ fixture で検出確認）を追加。
- 第34ラウンドのレビュアー1は、DSH 常駐デーモンが本環境のサンドボックスで起動できない（子プロセスのプロファイル書き込みが EPERM、クリーン環境では Node の CSPRNG 初期化が失敗）ため、**同一モデル（z-ai/glm-5.3-flash, reasoning_effort=max）・同一ペルソナ・同一プロンプトを NVIDIA NIM API へ直接送信**して実施した（review/nim_review.py）。判定・指摘水準は従来ラウンドと同じ。

## 再生不具合の原因究明・LUT 置き場・フレーム保存・README 改訂（第35ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 35 | **完全Go**（重大 0 / 中 2 / 低 7。中 2 件は下記のとおり実測で補完） | **完全Go** |

- 中 1（回転×10bit の pix_fmt 分岐が実証されていない）→ **実測**: 10bit HEVC + rotation=90 のソースに 2098x1180 クロップ → 出力 hevc Main 10 / 2098x1180 / yuv420p10le（10bit 維持を確認）。
- 中 2（回転動画のフレーム保存の向き未確認）→ **実測**: フレーム抽出は表示向き（1920x886、アスペクト 2.167 = 2556x1180 と一致）で、横向きの正しい画像が保存される。
- 低 4/5/7 を反映: video の MediaError 種別で文言を出し分け、案内文を書き出しモードに追従（再エンコード時に「無変換です」と言わない）、前回の保存先が無効な場合はビデオフォルダへフォールバック。
- 低 3（クロップ座標の意味変化）と低 8（LUT 変更 API の露出）は docs/DELIVERY.md に仕様メモとして明記。

## Tailscale（tailnet）対応（第40・41ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 40 | 条件付きGo（中2: DNSName の末尾ドット／*.ts.net のマッチ方式の確認） | 完全Go |
| 41 | **完全Go**（中1・中2 の解消を実測で確認。残りは非ブロッキングの軽微メモ2件のみ） | — |

- 実測: /api/health を tailnet アドレス 100.70.95.77 で 200、Host を MagicDNS 名 desktop-515r9ue.tail0340.ts.net で 200、Host を evil.example.com で 403、LAN（192.168.0.200）で 200。
- 軽微メモのうち「Host が .ts.net そのもの」は長さガードとテストを追加済み（連続ドットの正規化は将来のバリデーション時のメモとして保留）。

## シークバー／IN・OUT の誤操作対策 実装（第42・43ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 42 | 条件付きGo（重要1: lostpointercapture の順序で確定済みドラッグが巻き戻る懸念／軽微6件） | **完全Go**（実ファイルを読んで実装を確認） |
| 43 | **完全Go**（重要1は実装順序＋テストで解消。残りはブロッカーなしの軽微3件） | — |

- 重要1 は実装が既に正しかった（tlUp が確定前に tlDrag をクリア、lostpointercapture は if(tlDrag) ガード）。追加テスト「cancel after up is a no-op」で実証。
- 軽微対応: ロックON時のドラッグ破棄、ソース切替時のドラッグ破棄、純粋なシークを Undo 履歴に入れない、マルチタッチ無視、実機診断用 tlState() 追加。
- テスト: tests/test_timeline_logic.js 24 ケース OK、SMOKE OK、check_ui_static OK、回帰 OK。
- 実機での操作感の確認はユーザー実施（README に操作方法を追記済み）。

## README 英語併記（第44・45ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 44 | 条件付きGo（中2: 見出しの曖昧さ・無変換/無劣化の訳し分け／低3件） | **完全Go**（両ファイルを読んで比較） |
| 45 | **完全Go**（中2・低3件の解消を確認。残りは任意の1件のみ） | — |

- README.md（日本語・既定）＋ README.en.md（英語）を相互リンクで切替。見出しは 30 対 30 で対応。
- 反映: Output folder (defaults and verification)／lossless (no re-encoding) の併記と因果の明示／LUT (colour conversion files)／File Explorer 表記／Features 見出し／用語集の調整。
- check_ui_static に両 README の切替リンク・導入4ステップ・特徴3点・画像・バッジ・Tailscale・タイムラインの静的ガードを追加（RESULT OK）。

## シークバー全面作り直し（◆ハンドル方式・第46ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 46 | **完全Go**（要確認1件: ドラッグ中に当たり判定を再評価していないか／軽微4件） | **完全Go**（実コードを読んで確認） |

- ユーザー指示: 元の単一バーに戻し、(1) シークバーは現在位置カーソルの当たり判定のみ (2) 現在位置カーソルの上部に◆ (3) IN/OUT の下半分に◆ (4) ◆付近を当たり判定に。
- GLM の要確認（ドラッグ中の再評価）は、pickTimelineTarget が tlDown のみで呼ばれ、tlMoveEv は掴んだ時点の tlDrag.target を使うことをコードで確認。静的ガード「handle is chosen only when grabbed」を追加。
- 境界テスト（±20px は当たり、±21px は外れ）8件を追加し、単体テストは27ケース全合格。

## シークバーを1.5倍に太くする（第48ラウンド）

| ラウンド | レビュアー1: GLM-5.3-flash (effort max) | レビュアー2: Agy gemini-3.8-flash-high |
|---|---|---|
| 48 | **完全Go**（幾何整合・帯境界の導出を確認。軽微3件） | **完全Go**（実コードを読んで確認） |

- バー 48px → 72px（1.5倍）、◆ 14px → 21px、現在位置の◆ top:3→5px、IN/OUT の◆ top:26→39px、カーソル線 3→4px、目盛り 12→18px、角丸 9→12px。
- 縦の当たり判定の境界を固定値からバー高さの半分（r.height/2）へ変更。GLM の軽微指摘（既定値の陳腐化）を受けて band は**必須引数**にした（既定値なし）。
- 検証: 単体テスト 27 ケース OK、スモーク OK、check_ui_static OK、実配信 HTML で height:72px / ◆21px / top:39px を確認。

## テスト設計レビュー（新しいゲート）

計画・成果物のレビューとは別に、**テスト設計そのもの**を独立にレビューする。

- 対象: `docs/TEST_DESIGN.md`（層の分担・網羅表・流出分析・提案）＋ `tests/` の実物。
- レビュアー: まず **GLM 5.3 Flash**（`review/nim_review.py review/testdesign_prompt.txt …`）。将来的に三者（Argon / GLM / Qwen）へ拡張。
- 合格基準: 「重大な欠陥: 無し」。指摘は `docs/TEST_DESIGN.md` §7 に対応、§8 に見送り理由を記録する。
- 運用: 機能追加・不具合修正のたびに §9 の流出分析へ1行追加し、同じクラスを二度流さない。

### 第1回（2026-11-08・GLM）

- 判定: **条件付きGo**（重大2・中5・軽3）。条件: ①オラクルの自己同調解消 ②DOM挙動/同期ループをゲート条件へ ③表の空白 ④非機能E2E。
- 対応: すべて実装（`tests/_harness.py` 新設・`tests/test_audio_ui_behaviour.js` 新設・`tests/e2e_jobs_cancel_parallel.py` 新設・境界仕様の明文化・build スタンプの内容ハッシュ化）。
- 実績: `require_current` が**旧ビルドのサーバを検出してテストを停止**（従来なら旧コードを検証して「合格」と誤報告していた）。
- 経過: 第1回 条件付きGo → 全条件実装 → 第2〜4回は証跡不足を含む条件付きGo → **第5回 完全Go（ゲート合格）**。
- この間に追加した資産: 内容レベル同期オラクル（マーカー素材）、独立パケット格子オラクル、DOM挙動テスト30件、非機能E2E、ビルド/ffmpeg 同一性の照合、デバッグログ（7日保持）。

## プレビュー方式変更（単一video＋書き出しプロキシ）（2026-11-10・第1〜15ラウンド）

| ラウンド | レビュアー1 | レビュアー2 | レビュアー3 |
|---|---|---|---|
| 1 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 2 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 3 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 4 | GLM: 条件付きGo | **Agy: 完全Go** | Qwen: 条件付きGo |
| 5 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 6 | GLM: 条件付きGo | **Agy: 完全Go** | Qwen: 条件付きGo |
| 7 | GLM: 条件付きGo | **Agy: 完全Go** | **Qwen: 完全Go** |
| 8 | GLM: 条件付きGo | **Agy: 完全Go** | Qwen: 条件付きGo |
| 9 | GLM: 条件付きGo | Agy: 条件付きGo | **Qwen: 完全Go** |
| 10 | GLM: 条件付きGo | **Agy: 完全Go** | **Qwen: 完全Go** |
| 11 | GLM: 条件付きGo | **Agy: 完全Go** | Qwen: 条件付きGo |
| 12 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 13 | GLM: 条件付きGo | Agy: 条件付きGo | Qwen: 条件付きGo |
| 14 | **GLM: 完全Go** | Agy: 条件付きGo | Qwen: 条件付きGo |
| 15 | **GLM: 完全Go**（要約版） | **Agy: 完全Go** | **Qwen: 完全Go** |

- 対象: `docs/PLAN_PREVIEW_PROXY.md`（v0.1 → v2.8）
- 結果: **三者完全Go**（Agy: v2.5/v2.6/v2.7, GLM: v2.4/v2.5/v2.6要約, Qwen: v2.6/**v2.9**）。最終確認は v2.9 で全員が完全Go。
- 備考: GLM は NVIDIA NIM の HTTP 504 が頻発したため、終盤は**要約版プロンプト**でレビューを実施。予備モデル（nemotron-3-ultra・承認済み）は v1.0/v1.3 でも完全Goを返し、判定の裏付けとした。
- 証跡: `review/agy_plan*.md`, `review/glm_plan*.md`, `review/qwen_plan*.md`, `review/*_final*.md`

## プレビュー方式変更の成果物レビュー（2026-11-10・第1〜9ラウンド）

| ラウンド | Agy gemini-3.8-flash-high | Qwen3.8 | GLM 5.3 Flash |
|---|---|---|---|
| 1 | 条件付きGo（Critical 2） | 条件付きGo（Critical） | 条件付きGo（Major） |
| 2 | 条件付きGo（Critical 1） | 条件付きGo（Critical 1） | 条件付きGo（Major 2） |
| 3 | 条件付きGo（Major 2） | 条件付きGo（Critical 2） | 却下（プロンプト切断で実装未提示） |
| 4 | **完全Go** | 条件付きGo（Major 1） | 条件付きGo（Major 2） |
| 5 | **完全Go** | 条件付きGo（Major 2） | **完全Go** |
| 6 | **完全Go** | 条件付きGo（Major 1） | （実行失敗） |
| 7 | **完全Go** | 条件付きGo（Major 1） | 条件付きGo（Major 1） |
| 8 | **完全Go** | 条件付きGo（Major 1） | 条件付きGo（Major 1） |
| **9** | **完全Go** | **完全Go** | **完全Go** |

- 結果: **第9ラウンドで三者完全Go（同一成果物）**。
- レビューで見つかり修正した実バグ: amix構文不正／共通後段(apad+atrim)脱落／variant判定fail-open／`.part`競合と失敗時残留／MP4ストリーム順（音声先行）／added音声未検証／負シフトのPTS再原点化欠落／proxy時の相対オフセット座標系／contentSigの弱さ／読み取り不能・probe失敗のエラー化／Windows長パス未統一。
- 証跡: review/agy_artifact*.md, review/qwen_artifact*.md, review/glm_artifact*.md

## プレビュー方式変更のテスト設計レビュー（GLM 5.3 Flash・第1〜5回）

| 回 | 判定 | 主な指摘 | 対応 |
|---|---|---|---|
| 1 | 条件付きGo | 検証項目とテストの対応が不明／framemd5 のオラクル不明確／残存リスク台帳の分断／トラバーサル未定義／LRU 競合未検証 | 検証項目⇔テスト対応表を新設、framemd5 は内容比較と明記、§11 に残存リスクを集約、キー検証と LRU のテストを追加 |
| 2 | 条件付きGo（Major4・Minor4） | 台帳の再分断／並行ビルドのテスト欠落／cleanup 保護の未検証／.part 削除がコードレビュー依存／表記ゆれ・PTS 取扱い・SKIP 空洞化・初回生成時間 | すべて実装（下記） |
| 3 | 条件付きGo（Major2・Minor4） | **.part 削除テストが fail-fast 経路に素通り**／並行ビルドのオラクルが空振り合格し得る（Minor: framemd5 の prefix 比較／§8 非機能段落の文意／§11 P1 の片方向参照／strict SKIP の適用範囲） | fail-fast と ffmpeg 起動後の失敗経路を分離（ランナー差し替え）、Barrier＋ユニークキー＋ジョブ件数で並行テストを強化、framemd5 を全フレーム一致に |
| 4 | 条件付きGo（Major1・Minor4） | 並行ビルドの **OK 行が実行ログに無い**（証跡不足）／時計由来シフトの400秒周期／.part 競合／SKIP ガードの範囲／`/api/jobs` の token 欠落 | 全スイートのチェック名付きログを提出、run token を uuid4 化、消失を5秒ポーリング、ガードの根拠明記、token 付与 |
| **5** | **完全Go** | 残存 Minor のみ（いずれも出荷阻害なし） | 任意対応: 二重タップ抑止の DOM テスト追加・sync 側の unique_shift も uuid4 化・token の意味論を §8 に注記 |

- 対象: `docs/TEST_DESIGN.md`（プレビュー方式変更の節・§8・§11）＋ `tests/` の実物。
- 実行ログの証跡: フィルタ(14)／同期・framemd5・mid-build(18)／キャッシュ・cleanup(26)／E2E(11)／静的ガード／DOM挙動(28) がすべて OK。
- このレビューで追加した資産: ffmpeg 起動後失敗経路の再現テスト（ランナー差し替え＋.part 検証）、Barrier による並行ビルド検証（uuid token でキャッシュキーを一意化＋ジョブ件数一致）、cleanup の実行中ジョブ保護テスト、SKIP 静的ガード（strict モード）、framemd5 全フレーム一致、反映ボタン二重タップ抑止の DOM テスト。
- **3つのゲート（計画・成果物・テスト設計）すべて完全Go で通過**。

## 表示倍率のヘッダー移動・設定の記憶バグ修正・音声タイミングのリセット（2026-11-10）

ユーザー報告: 「表示倍率が書き出しカードにあるのは意味がわからない。ヘッダーに移動」「再読み込みすると倍率が戻る。設定の保存漏れを再チェック」「新しい動画を読み込んだら音声タイミングはリセットされるべき」。

### 計画レビュー

| 回 | GLM 5.3 Flash | Agy gemini-3.8-flash-high |
|---|---|---|
| 1 | 条件付きGo（ガード位置・crop復元・保存頻度・追加音声の扱い） | 条件付きGo（同期化・ドラッグ保存・分類） |
| 2 | 条件付きGo（R2-1〜R2-7） | **完全Go** |
| 3 | 条件付きGo（R3-1: pendingCrop の消費順。修正 diff 提示で完全Go可と明言→反映） | — |
| 判定 | **完全Go**（R2/R3 の条件をすべて修正・テストで固定） | **完全Go** |

### 成果物レビュー

| 回 | GLM 5.3 Flash | Agy gemini-3.8-flash-high |
|---|---|---|
| 1 | 条件付きGo（M1/M2・Minor 4） | **完全Go** |
| 2 | 条件付きGo（メッセージ上書き・setSelectValue・順序証跡） | — |
| 3 | 条件付きGo（MJ1 クロップの素材跨ぎ・Minor 8） | — |
| 4 | 条件付きGo（LUT「なし」・プレビュー生成中の切替・zoom 二重保存） | — |
| 5 | 条件付きGo（LUT「なし」・プレビュー生成中の素材切替・zoom 二重保存） | — |
| 6 | **完全Go**（上記3件の修正と回帰テストを確認） | **完全Go**（最終差分を確認） |

### テスト設計レビュー（GLM 5.3 Flash）

| 回 | 判定 | 主な指摘 |
|---|---|---|
| 1 | 条件付きGo | 全緑ログの欠落／静的ガードの空振り／クロップ検証が実経路でない |
| 2 | 条件付きGo | e2e の旧ビルド FAIL／スライスの -1 空振り／クロップのオラクル非識別 |
| 3 | 条件付きGo | ログ件数・静的ガード全文・2本目全画面の実経路 |
| 4 | （採点不能: 推論が max_tokens に達し本文が空） | — |
| 5 | 条件付きGo | 保存経路の固定待ち／追加音声まわりの非保存検証／ハーネス限界の記録 |
| 6 | 条件付きGo | 上記 Major 3件・Minor 5件（すべて小規模修正） |
| 7 | **完全Go** | 主系 GLM は NIM 504 が継続したため、**承認済み予備モデル（nemotron-3-ultra）と Agy の2者**で最終確認。両者とも完全Go |

- 実バグとして見つかり修正したもの:
  1. 初期化末尾の `setAudioShift()` が `saveSettings()` を呼び、非同期復元より先に保存データを**既定値で上書き**（再読み込みで全設定が戻る）。復元を同期化し、復元完了まで保存を無効化する `settingsReady` を導入。
  2. クロップ変更（プリセット・枠ドラッグ）が保存を呼んでいなかった。ドラッグ中は抑制し pointerup/pointercancel で1回保存。
  3. クロップ復元が input 値の set だけで `crop` 変数に反映されていなかった。メタデータ確定後に `applyPendingCrop()` でクランプ適用。**保存元の sourceId にのみ復元**（別素材へ引き継がない）。
  4. 音声タイミングが全体設定として保存され、別素材に前回の補正値が残る設計だった。素材固有のセッション状態へ再分類し、動画を開くたびにリセット（モード・追加音声・再エンコード・実行中の同期解析・未完了プレビューを含む）。
  5. プレビュー反映中に素材を切り替えると、旧プレビュー URL への復帰が新素材の読み込みを壊し得た。リセットを `setVariant` の前に移動し、完了が遅れたビルド結果はトークンで破棄。
  6. LUT を「なし」に戻しても保存されない経路（pendingLut フォールバック）を `lutListLoaded` で解消。

- テスト: 全スイート **308 checks OK / FAIL 0**（静的ガード 191 件・設定往復 41 件・音声UI 40 件・E2E 11 件・smoke・unit）。新規 `tests/test_settings_persist.js` は同一 localStorage で2回ロードし、実 `selectSource` / `loadedmetadata` を駆動して復元・リセット・LUT 解除・sourceId 一致を検証する。


## 音声を無変換で遅らせるオプション（`delayNoReencode`）（2026-11-10）

ユーザー要望: 「音声エンコードについて、2を無変換オプションとして実装。まだ、デフォルトでなくてよい。」
（事前検討の結論: 無音を先頭に付ける既定方式は AAC の 21.33ms フレーム量子化と +42.7ms のエンコーダ・プリミングで数10ms ずれる。音声を再エンコードせず、コンテナ開始位置（mp4/mov の edit list、Matroska の block timestamp）で遅らせる方式を任意オプションとして実装）

### 計画レビュー

| 回 | GLM 5.3 Flash | Agy gemini-3.8-flash-high |
|---|---|---|
| 1 | **完全Go** | **完全Go** |

- 設計: `delayNoReencode`（既定 OFF）。ON + 正のずらし + 区間先頭に遡る余裕なし + コンテナが edit list / block timestamp 対応のとき、音声パケットを無変換のままコンテナ timestamp で遅延（`audio.delayMode="timestamp"`）。非対応コンテナ（`NO_ELST_CONTAINERS`）は理由警告付きで従来の adelay 再エンコードへフォールバック。既定は完全に不変。

### 成果物レビュー

| 回 | GLM 5.3 Flash | Agy gemini-3.8-flash-high |
|---|---|---|
| 1 | 条件付きGo（Minor 1〜3: bool 解釈・dropped 記録・警告の過大表現） | **完全Go** |
| 2 | **完全Go**（Minor 1〜3 の修正を確認） | **完全Go** |
| 3（警告矛盾の修正後・再審査） | **完全Go** | **完全Go**（指摘 0 件） |

- 回1で修正した実装上の指摘: (1) exports 側の緩い bool 解釈（`bool("false")==True`）を `is True` に統一、(2) `audioTiming=false` の dropped 記録を `is not None` に、(3) 警告を「映像と元の音声は無変換」に限定し追加音声再エンコード時は付記。

### テスト設計レビュー

| 回 | GLM 5.3 Flash | Agy gemini-3.8-flash-high |
|---|---|---|
| 1 | 条件付きGo（Major 2: MKV/フォールバックの E2E 欠落、Minor 6） | — |
| 2 | 条件付きGo（Minor 5: ログ文字化け・添付切断・mkv lossless・格子ガード・半開区間） | — |
| 3 | 条件付きGo（Major 2: **timestamp 経路の矛盾警告を発見**、添付切断の再発） | 条件付きGo（同じ矛盾警告を独立に発見） |
| 4 | **完全Go** | **完全Go**（新規指摘は非ブロッキングの Minor のみ） |

- テスト設計レビューで見つかり修正した実バグ: `start_export` の「re-encode ルート向け」音声警告ブロックが `reencode` 判定の外にあり、lossless 経路（timestamp 経路・コンテンツ遡り経路）でも「音声のみ再エンコードします（無変換ではなくなります）」を誤って出していた。ブロック全体を `if reencode:` で囲み、E2E 9b/9c に「timestamp 経路の警告に『再エンコード』が混ざらないこと」の否定検証を追加。flv フォールバックの重複警告も 3 件→2 件に整理。
- 追加したテスト: unit の `_audio_plan` 13 ケース（既定/ON/mp4/matroska/elst 非対応/余裕あり/負/追加音声/start_time 欠落/音声のみ）、E2E 9b（mp4・ビット一致・timestamp・格子一様性・映像コピー・否定警告）、9c（matroska 同等 + lossless 断言）、9d（flv フォールバック + 理由警告 + md5 不一致）、既定 OFF の回帰、不正 bool の 400、UI 静的ガード 6 件、設定永続化・音声 UI 挙動・preview 非送信。
- 実測: E2E `RESULT: OK`（build d8cb94a6d840 = 作業ツリー、音声パケット md5 一致・173 packets・格子 [0.023219, 0.02322]）、UI 静的ガード 196 checks / 0 fail、unit OK、音声系 E2E（sync/upload/lossless/export_ops/api）すべて OK。
- 残存する非ブロッキング Minor（レビュアー指摘・出荷を妨げない）: advance lossless 経路の否定警告検証なし／mute + `delayNoReencode` の組み合わせ未検証／9c の肯定警告検証・9d の逆方向否定検証が非対称／チャプター不在と `start_time` 欠落時 timestamp の E2E 裏付けは未実施（前者は静的ガードと仕様明記、後者は unit のみ）。`re_opts = options` の else 枝は no-op（可読性のみ）。

- 既知の制約（意図した仕様）: 開始位置（edit list / block timestamp）を無視する再生アプリでは遅延が反映されない（既定を再エンコードにしている理由）。この経路ではチャプターが出ない。プレビューは焼き込みのため ON/OFF で聴感は変わらない（書き出しのみ）。
