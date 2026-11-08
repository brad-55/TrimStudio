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