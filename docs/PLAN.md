# Trim — 無変換（Lossless）動画トリミングツール 実装計画

版: 0.4（追加要望反映版。API の契約は docs/API.md を正とする）
日付: 2026-11-05
ワークスペース: L:/dev/Trim
待受: 0.0.0.0:8003（LAN 内限定、IPv6 併用）

## 0. 改訂履歴とレビュー状況

- 0.1 初版。レビュアー2（Agy gemini-4-argon-high）とレビュアー1（DSH/NIM z-ai/glm-5.3-flash,
  reasoning effort max）がいずれも「条件付きGo」。
- 0.2 両レビュアーの全指摘を反映（対応表は §17）。UI は本人とローカル Qwen
  （http://127.0.0.1:8080/v1, qwen3.8-flash-next-iq3_s）の二重実装とし、ユーザーが採用を決める。
- 0.3 第2ラウンド指摘を反映: キーフレーム索引の ffprobe 取得方法（§3.6）、exact 終端の全デコード
  検証、inSnap=next の整合、API options への inSnap/outMode、DELETE の非破壊化、既定トークン配布、
  許可ルート既定、media の variant と attached_pic 除外、LRU のアクティブ除外、デュアルスタック
  待受、再エンコードの A/V 同期オプション、二重 UI のパリティ基準、対応表の修正。
- 0.4 実装中の追加要望と確定仕様を反映（API の契約は docs/API.md を正とする）:
  - §5 `POST /api/fs/mkdir {path}`（出力先フォルダ作成。許可ルート外は 400、予約名・禁止文字はサニタイズ）。
  - §3.2/§5 exports の `videoBitrate` / `audioBitrate`（kbps）。映像は未指定なら CRF、音声は未指定なら元の音声
    ビットレートを踏襲（不明時 192kbps）。不正値は 400。
  - §5 / docs/API.md: source の `bitRate` / `videoBitRate` / `audioBitRate` / `meta` / streams 詳細
    （profile・level・色・channel_layout・nb_frames 等）。既存ソースは開き直し時に再取得し索引は維持。
  - 音声ソース（mp3/m4a/aac/wav/flac/ogg/oga/opus/wma/aif/aiff）のトリミング対応（索引は即 ready、
    FLAC のみ可逆再エンコードで STREAMINFO 補正）。
  - 出力コンテナの明示指定（許可16種: mp4/mov/matroska/webm/ipod/mp3/adts/wav/flac/ogg/asf/aiff/mxf/mpeg/avi/flv）と、格納不能・単一音声コンテナ制約・未知値の 400。
  - 出力先に残った古い `.part` の自動掃除、UI の出力先エクスプローラ。

## 1. 目的とスコープ

スマートフォン（モバイルブラウザ）から操作し、PC 上の動画またはアップロードした動画を
「再エンコードせずに（無変換で）」トリミングして書き出す Windows 用ツール。

必須:
- 無変換であること（映像・音声ストリームを再エンコードしない）
- Windows で動作
- UI は Web（モバイル最優先）
- 動画再生（モバイルで再生不能なコーデック・高ビットレートも扱う）
- ソースはモバイルからのアップロード、または PC ストレージ上のファイル
- PC 上の動画を選ぶファイルエクスプローラ
- シークバーで映像を見てトリミング位置を決定
- 時間の直接入力でトリミング位置を決定
- コマ送りで位置を調整
- 書き出し先の指定（既定: PC ソースは元フォルダ、アップロードは Windows のビデオフォルダ）
- UI の二重実装（本人版とローカル Qwen 版）。ユーザーが比較して採用を決める

任意（無変換不可・劣化最小化）:
- LUT 適用（log 素材）、スタビライザー（ffmpeg vidstab）、クロップ

## 2. 用語

- 無変換カット: パケットをコピーするカット（ffmpeg -c copy）。
- キーフレーム: 単体でデコードできる I フレーム。無変換の開始境界に必須。
- GOP: キーフレームから次のキーフレーム直前まで。
- Us: マイクロ秒（本ツールの正準時刻単位）。
- inSnap: 開始位置のスナップ規則。prev（既定）| next。
- outMode: 終了位置の規則。exact（既定）| keyframeBefore | keyframeAfter。
- 実カット区間: 実際に出力へ入る区間（目的区間との差を UI 表示）。
- プレビュー: 表示・シーク用の軽量プロキシ。出力とは別物。
- 直接再生: ブラウザが元ファイルをそのまま再生できること。
- スマートカット: 境界 GOP のみ再エンコードする非無変換の高精度カット（v1.1）。

## 3. 確定した設計判断

### 3.1 無変換カットの定義（R8 解消）

- 実装は ffmpeg の入力前 -ss と -t によるパケットコピー。開始はキーフレームでなければならない。
- inSnap 既定 prev: startUs 以前で最大のキーフレーム。next も選択可。inSnap=next で次の
  キーフレームが endUs を超える場合はバリデーションエラーとし、inSnap=prev へ自動フォールバック
  する（負の尺を防ぐ）。
- outMode 既定 exact: -t で endUs に達するまで書き出す。末尾 GOP は途中で切れ、B フレームの
  参照が欠けて末尾 1〜数フレームがデコードエラーになり得るため「無条件に再生可能」とは断定しない。
  keyframeBefore（endUs 以前の最大キーフレームで終了）と keyframeAfter（endUs 以降の最小
  キーフレームまで含める）も選択可。
- 既定は inSnap=prev / outMode=exact。UI は目的時刻・実カット区間・差分を常時表示する。
- exact は §13 で全フレームデコード検査（デコードエラー 0・末尾フレーム欠落なし）と主要プレイヤで
  検証する。末尾破損が確認された場合は既定を keyframeBefore に変更する（R1 の判断材料）。
- faststart は mp4/mov/m4a のときのみ付与（既定 ON、巨大出力では OFF 可）。
- 出力は常に別ファイル。完全なフレーム精度が必要な場合は v1.1 のスマートカット（境界 GOP のみ
  再エンコード、非無変換と明示）を選べるようにする。

### 3.2 ストリームマッピングとコピー可否判定

- エクスポート前に ffprobe で全ストリームを列挙し、出力コンテナ×コーデックの対応表で copy
  可否を判定する。
- 既定マップは -map 0:v:0? -map 0:a? -map 0:s?（映像 1 本・音声・字幕）。データ・添付
  （codec_type=data/attachment）は既定で除外する。disposition=attached_pic のカバー画像は映像
  ストリームであっても選択対象から除外する。MKV 出力時のみ添付を含められる。
- 対応表でコピー不可のストリーム（例: PCM 音声→MP4、ASS 字幕→MP4）は既定で除外し、UI に
  警告する。全 include ストリームを格納できない場合は MKV への remux を提案する（remux も無変換）。
- 個別指定は -map 0:{index}。複数映像がある場合は UI で 1 本を選択。
- -map_metadata 0 を付与。チャプターは出力コンテナが対応する場合のみ -map_chapters 0。
- 出力コンテナ既定: ソースコンテナが全 include ストリームを格納可能ならソース同一、否則 MKV。
  UI で変更可（API の options.container、許可16種。未知値・格納不能・単一音声コンテナ制約は 400）。
- 再エンコード時は UI から映像・音声のビットレート（kbps）を指定できる（options.videoBitrate /
  audioBitrate）。映像は未指定なら CRF、音声は未指定なら元の音声ビットレートを踏襲。音声のみの
  再エンコードはコンテナ別コーデック表（aac / libopus / wmav2 / libmp3lame / mp2 / pcm_s16le / flac）を使う。

### 3.3 時刻表現と精度

- 正準単位は整数マイクロ秒（Us, int64）。API は startUs / endUs / tUs / fromUs / countFrames。
- 各ストリームの time_base を保持し、キーフレームの PTS は元の有理数とマイクロ秒丸め値の双方を
  保持する。
- ffmpeg へは秒（小数最大 9 桁）で渡す。開始はキーフレームの実 PTS を用い、丸めでキーフレームを
  取り逃さない。必要なら time_base 1 tick 手前のマージンを検討し、§13 のテストで確定する。
- 目標時刻と実カット時刻の差は Us で UI に表示する。
- framemd5 比較は pts/dts 行を除外し表示順に整列したハッシュ列で行う（make_zero の影響を排除）。

### 3.4 再生不能コーデック対応・直接再生可否

- 直接再生の自動判定: コンテナが mp4/mov/webm かつ映像が H.264 8bit（yuv420p）かつ音声が
  AAC/MP3/無音。加えてブラウザの canPlayType と実再生イベント（loadedmetadata / error）で確認。
- 条件を満たさない、または error 発生時はプロキシ生成を提案する。ユーザー操作でいつでも手動
  切替できる導線を設ける。
- プロキシ: 長辺 1280px 以下、H.264 yuv420p、CRF 28、preset veryfast、AAC 128kbps、faststart。
  HDR/10bit は zscale と tonemap で SDR（bt709）へ変換し、プレビュー専用と明記する。
- フレーム抽出: JPEG、長辺 1280px 以下（クエリで変更可）。HDR はトーンマップ。抽出結果は
  タイムスタンプでキャッシュし、コマ送り時は周辺を先読みする。

### 3.6 キーフレーム索引とフレーム時刻の取得方法

- キーフレーム索引: ffprobe の
  ffprobe -select_streams v:0 -show_packets -show_entries packet=pts,pts_time,dts_time,flags
  で K フラグのパケットのみを抽出し、DTS で整列したうえで PTS を採用する。デコードを伴う
  -show_frames は使わない。
- 全区間索引は M1 のバックグラウンドジョブで構築し進捗を SSE で通知する。基本メタ取得のみを
  同期で行い open をブロックしない。
- 範囲取得（/frames）と現在位置周辺のフレーム時刻は ffprobe の
  -read_intervals {startSec}%+{durationSec} で対象区間のみを走査する。
- 性能基準: 数十 GB の 4K 動画でキーフレーム索引の構築が既定目標 5 分以内に収まることを §13 で検証する。

### 3.5 ffmpeg 同梱

- 探索順: L:/dev/Trim/tools/ffmpeg/bin → PATH。どちらも無い場合のみダウンロード。
- ダウンロード対象は特定の固定リリース（gyan.dev の固定バージョン、または BtbN の特定タグ）とし、
  対応する既知 SHA-256 を config に保持して検証する。master-latest のような移動 target は使わない。
- ハッシュ更新は専用スクリプトでリリースの checksum を取得して更新する手順を用意する。
- GPL ビルドを含むライセンスと入手元を README に明記する。

## 4. アーキテクチャ

- バックエンド: Python 3.13 + FastAPI + uvicorn（L:/dev/Trim/.venv）。
- フロントエンド: 静的 SPA。web/（本人体）と web-qwen/（ローカル Qwen 体）の二重実装。
- 配信: / → 本人版、/qwen/ → Qwen 版、/compare → 両者を並べる比較ページ。ユーザー採用後は
  採用版を / の既定へ昇格する（設定で切替）。
- 永続化: SQLite（data/trim.db）。ソース、キーフレーム、フレーム時刻、プロキシ、サムネイル、
  ジョブ履歴。
- 作業領域: data/work（プロキシ、フレームキャッシュ、スプライト、LUT 作業コピー、一時ファイル）。
- ログ: data/logs。
- データフロー（無変換）: ソース選択 → 基本メタ同期取得 → キーフレーム索引はバックグラウンド →
  必要ならプロキシ（進捗 SSE）→ 再生・シーク・コマ送り → IN/OUT 決定 → 出力先決定 →
  ストリーム互換判定 → ffmpeg -c copy 実行 → 進捗と結果を SSE 通知 → 差分表示。

## 5. バックエンド API（UI 契約）

- 時刻パラメータはすべて整数マイクロ秒（Us）。状態変更は同一オリジン検証と X-Trim-Token を要求。
- GET  /api/health                     稼働確認、版、ffmpeg 状態
- GET  /api/config                     許可ルート、既定出力先、上限値、モード、UI 既定
- GET  /api/roots                      ブラウズ可能ルート一覧
- GET  /api/browse?path=...            ディレクトリ一覧（動画・音声拡張子フィルタ）
- POST /api/fs/mkdir                   { path } → { path } 出力先フォルダ作成。許可ルート外・空名は 400、
                                        予約名や禁止文字はサニタイズ（予約名は _CON 等、ドット入り名は保持）
- POST /api/sources/open               { path } → { sourceId }
- POST /api/sources/upload             multipart → { sourceId, storedPath }（検証済み動画のみ）
- GET  /api/sources                    管理下ソース一覧
- GET  /api/sources/{id}               基本メタ（ストリーム、尺、fps、直接再生可否）
- GET  /api/sources/{id}/keyframes     キーフレーム（Us）と索引の準備状態
- GET  /api/sources/{id}/frames?fromUs=&countFrames=  フレーム時刻（Us）
- GET  /api/sources/{id}/media          Range 配信（variant で原盤/プロキシを選択）
- GET  /api/sources/{id}/frame?tUs=    指定時刻の JPEG
- POST /api/sources/{id}/proxy         プロキシ生成開始 → { jobId }
- GET  /api/sources/{id}/sprite        シークバー用スプライト
- DELETE /api/sources/{id}             登録情報と派生キャッシュのみ削除。PC 上の元ファイルは削除しない。
                                        アップロード保管コピーは既定で削除（?keepUpload=true で保持）。
- POST /api/exports                    { sourceId, startUs, endUs, mode, options, outputPath? } → { jobId }
                                        options: { inSnap: prev|next, outMode: exact|keyframeBefore|keyframeAfter,
                                        lut, stabilize, crop, order, audioReencode, videoBitrate, audioBitrate,
                                        container, outputPath }
                                        videoBitrate/audioBitrate は kbps。映像は未指定なら CRF、音声は未指定なら
                                        元の音声ビットレートを踏襲（不明時 192kbps）。不正値は 400。コンテナは許可16種で、
                                        未知値・格納不能・単一音声コンテナ制約は 400。
- GET  /api/sources/{id}/media?variant=original|proxy  Range 配信（既定 original）
- GET  /api/jobs/{id}                  ジョブ状態
- GET  /api/jobs/{id}/events           SSE（Last-Event-ID に対応し、リングバッファから再送）
- POST /api/jobs/{id}/cancel           キャンセル（ffmpeg 終了を待って一時ファイルを削除）
- GET  /api/luts                       LUT 一覧（L:/dev/Trim/luts）
- POST /api/paths/validate             { path, mustExist } → 書込可否、空き容量、必要容量推定
- エラーは { code, message, detail }。ジョブ同時実行は グローバル最大 2、ソース毎にエクスポート 1・
  プロキシ 1 を既定とし config で変更可。

## 6. 無変換エクスポート仕様

前処理:
1. ffprobe で全ストリーム取得。
2. コンテナ×コーデック対応表で include ストリームと copy 可否を決定。
3. キーフレーム索引から実カット区間（inSnap/outMode）を算出。

コマンド例（MP4 出力、faststart 有効）:

    ffmpeg -hide_banner -nostdin -ss {actualStartSec} -i {src} -t {durationSec}
      -map 0:0 -map 0:1 ... -c copy -map_metadata 0
      -avoid_negative_ts make_zero -movflags +faststart {out}.part.{ext}

- -movflags は mp4/mov/m4a のみ。MKV/WebM では付与しない。
- 出力は同ディレクトリの一時ファイル .part に書き、正常終了と簡易検証（ffprobe でストリーム数・
  コーデック・尺）後にアトミック rename する。失敗・キャンセル時はプロセス終了を待って削除する。
- 通常エクスポート時の検証は高速検査のみ。全フレーム framemd5 はテスト（§13）と受け入れ検証で行う。

## 7. 再エンコード仕様（任意・劣化最小化）

- API は mode=lossless|reencode。reencode 時は options に lut / stabilize / crop を任意に組み合わせる。
- フィルタ順序（既定）: vidstabtransform → crop → lut3d。理由: スタビライズで生じる黒縁を
  crop で除去する。詳細オプションで順序を変更できる。vidstab は 1 パス目 detect・2 パス目
  transform の双方で同一のトリミング区間（-ss / -t）と同一の前段フィルタを使う。
- フィルタ引数のパスは ASCII 名の作業ディレクトリに LUT を作業コピーし、相対ファイル名で渡す。
  絶対パスを渡す場合は区切りをスラッシュへ置換し、コロンをエスケープする規則を ffmpeg_tools に
  実装する。
- LUT: 16bit 中間（format=gbrp16le 等）で lut3d を適用し、最終 pix_fmt へ変換。LUT 適用後の色
  メタデータは bt709 を既定とし、「ソースのタグを維持」も選択可。HDR→SDR トーンマップは対象外。
- スタビライザー: vidstabdetect（shakiness, accuracy）→ vidstabtransform（smoothing, optzoom）。
- クロップ: crop=w:h:x:y、偶数丸め。出力解像度はクロップ後サイズとし、元解像度へ再拡大しない。
- エンコーダ別パラメータ表:
  - libx264: -preset slow -crf 16 -pix_fmt yuv420p -tune film -profile high
  - libx265: -preset medium -crf 18 -pix_fmt yuv420p10le または yuv420p -tag:v hvc1
  - h264_nvenc: -preset p5 -rc vbr -cq 19 -pix_fmt yuv420p（10bit 非対応）
  - hevc_nvenc: -preset p5 -rc vbr -cq 21 -pix_fmt p010le
  - -tune film は libx264 のみ。x265 には付けない。
- 音声は既定で copy。copy 不可時のみ再エンコード（AAC 192kbps 等）。再エンコードモードで
  非キーフレームから開始する場合は A/V 先頭ズレが生じ得るため、詳細オプションでタイムスタンプ
  補正または音声再エンコードを選べるようにする。
- 非無変換であることを UI で明示し、実行前に確認を取る。

## 8. 出力先・ファイル命名

- PC ソース: 既定はソースと同じディレクトリ。アップロード: 既定は Windows のビデオフォルダ
  （SHGetKnownFolderPath(FOLDERID_Videos)、失敗時はホーム配下の Videos）。
- 任意ディレクトリを選択可（許可ルート内、書込可否と空き容量を検証）。
- 出力名: 元名をサニタイズし、Windows 予約名・禁止文字を除去。時刻はコロンを含まない形式
  （例: 00h01m23s456）。パス全体が 240 文字以内になるよう base を切り詰める。上書き禁止、
  連番で衝突回避。

## 9. セキュリティ（要件 11）

- 主対策: 送信元 IP を検査し、プライベートアドレスのみ許可する。
  10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, ::1, リンクローカル,
  IPv6 ULA（fc00::/7）, IPv4 射影（::ffff:a.b.c.d は IPv4 として正規化して判定）。
- 待受は IPv4 と IPv6 のデュアルスタックを既定とする。Windows では host=0.0.0.0 だけでは IPv6 を
  受けられない場合があるため、IPV6_V6ONLY=0 の AF_INET6 ソケット（::）を用意して uvicorn に渡すか、
  0.0.0.0 と :: の双方で待受ける構成を main.py で採る。IPv6 接続も許可範囲内なら通す。
- Host 検査: localhost、ループバック、起動時に列挙した自ホストの全インターフェース IP（ポート
  任意）を許可。ホスト名は解決結果が自ホスト IP の場合のみ許可。許可集合は起動時とネットワーク
  変更時に更新する。
- CSRF / DNS リバインディング対策: 状態変更 API は同一オリジン検証（Origin/Referer）と
  X-Trim-Token を要求する。既定（強モード OFF）では配信する index.html に起動時トークンを埋め込み、
  UI がそれを読み取って送る。トークンは CSRF 対策であり、LAN 内他端末の制限ではないと明記する。
- オプションの強モード（既定 OFF）: 起動時に PC コンソールと QR でトークンを提示し、入力後に
  HttpOnly; SameSite=Strict Cookie を発行する。これにより media / img / EventSource も保護し、
  LAN 内他端末からの利用を制限できる。
- メディア配信: 動画系 MIME のみ、X-Content-Type-Options: nosniff、Content-Disposition: inline。
- アップロード: 拡張子と ffprobe による実体検証。保存名はサーバ生成のサニタイズ名とし、検証済み
  動画拡張子へ正規化する。サイズ上限と空き容量を検証。
- パス安全: 許可ルートを正規化し、realpath（シンボリックリンク・ジャンクション解決後）がルート
  配下であることを検証。閲覧は動画拡張子に限定。
- ffmpeg は shell を介さず引数配列で起動する。

## 10. 作業領域・クリーンアップ・Windows 対策

- data/work は容量上限（既定 20GB または空きの 10% の小さい方）と LRU 退避を持つ。
  再生中・登録中のアクティブソースと実行中ジョブのプロキシ・フレームキャッシュは退避対象外とする。
- 起動時に孤立した一時ファイルと .part を削除。DELETE /api/sources/{id} でソースと派生キャッシュ
  を削除。
- /api/paths/validate は必要容量の推定（総ビットレート×尺）と空き容量を返す。
- Windows: 非 ASCII パスは Unicode のまま ffmpeg へ渡す。240 文字超は拡張長パス接頭辞を付与
  （longPathsEnabled の状態を検出して使い分け）。予約名（CON, PRN, AUX, NUL, COM1..9, LPT1..9）を
  回避。ファイルロック: ffmpeg 終了待ち後に削除・rename。
- ffmpeg は CREATE_NO_WINDOW で起動。キャンセルはプロセスツリーを終了。

## 11. ディレクトリ構成

    L:/dev/Trim/
      app/                 バックエンド（Python）
        main.py config.py security.py ffmpeg_tools.py sources.py media.py exports.py jobs.py db.py
        bootstrap_ffmpeg.py
      web/                 本人実装の UI
      web-qwen/            ローカル Qwen 実装の UI
      docs/PLAN.md docs/API.md docs/REVIEW.md
      review/              レビュー用スクリプト・プロンプト・ログ
      tools/               開発補助（dsh_rpc_client.py 等）
      luts/                LUT 配置
      data/                DB・作業領域・ログ（git 管理外）
      tests/
      README.md requirements.txt start.cmd config.example.json

- config.example.json の既定: allowedRoots は全固定ドライブのルート、denyRoots は Windows/System32 等。
  出力既定は PC ソースは元ディレクトリ、アップロードは Videos。requireToken=false（CSRF トークンは常に
  有効）、strongMode=false。

## 12. 実装フェーズ

- M0 基盤: venv、依存、ffmpeg ブートストラップ、設定、起動、IP 制限とトークン検証を最初から有効化。
- M1 ソース: エクスプローラ、アップロード、ffprobe 基本メタ、キーフレーム索引（バックグラウンド）、
  ソース一覧・削除。
- M2 プレビュー: Range 配信、プロキシ（進捗）、フレーム抽出と先読み、スプライト。
- M3 カット: ストリーム互換判定、無変換エクスポート、inSnap/outMode、出力先、一時ファイルと
  アトミック rename、高速検証。
- M4 UI（二重実装）: 本人版（web/）とローカル Qwen 版（web-qwen/）。同一 API 契約。M4 のパリティ
  基準はコア機能（ソース選択、再生・シーク、IN/OUT 時間入力、コマ送り、出力先、進捗）の両実装での
  動作とする。M5 の任意機能（LUT/スタビ/クロップ）は本人版で先に実装し、Qwen 版はコア採用後に
  必要なら追随する。/compare で比較し、ユーザーが採用を決定。
- M5 任意機能: LUT、スタビライザー、クロップ。
- M6 仕上げ: README、ファイアウォール手順、性能調整。
- M7 受け入れ: モバイル実機確認、無変換検証。

各マイルストーン完了時にテストを実行し、計画レビューと成果物レビューで完全 Go を得る。

## 13. テスト

- 単体: 時刻換算、inSnap/outMode、パス安全、ffmpeg 引数生成、ファイル名サニタイズ、コンテナ対応表。
- 統合（無変換の機械検証）: ffmpeg testsrc で生成した H.264/AAC MP4 と H.265 MKV を全モードでカット。
  - 映像・音声がコピーであること（コーデック・解像度・pix_fmt・パケット数の整合）。
  - pts/dts を除外し表示順に整列した framemd5 ハッシュ列がソースの該当区間と一致すること。
  - 実カット区間が inSnap/outMode の定義どおりであること。
- 終端 exact の再生互換: ffmpeg -v error -i out -f null - で全フレームデコードしエラー 0 と末尾
  フレーム欠落なしを確認し、主要プレイヤでも再生確認する。
- 非互換ストリーム: PCM 音声・ASS 字幕・データストリーム付きで既定除外と警告、MKV remux を確認。
- 異常系: 巨大ファイル、VFR、音声無し、複数音声、字幕、非 ASCII パス、長パス、破損ファイル。
- 再エンコードの A/V 同期: -ss と音声 copy の組み合わせで先頭ズレを測定し、タイムスタンプ補正
  または音声再エンコードの詳細オプションを検証する。
- 性能: 数十 GB 動画で open がブロックしないこと、キーフレーム索引が 5 分以内に完了すること、
  コマ送りがキャッシュで高速なこと。
- セキュリティ: 非プライベート IP を 403、IPv6 ULA を許可、IPv4 射影の正規化、Host 不一致拒否、
  トークン欠落拒否、アップロードの MIME/nosniff。
- UI: 主要操作の E2E（モバイルビューポート）。両実装に同一シナリオを適用。

## 14. レビュー運用（承認済み）

- レビュアー1: DSH 経由 NVIDIA NIM z-ai/glm-5.3-flash（reasoning effort max）。
- レビュアー2: Agy gemini-4-argon-high（最高エフォート相当）。
- 予備: DSH 経由 NVIDIA NIM nvidia/nemotron-3-ultra-550b-a55b（承認済み）。
- 元指定の z-ai/glm-5.3 と moonshotai/kimi-k3 は NIM で EOL のため、上記代替をユーザーが承認。
- エフォートは各モデルの最高設定を使う。
- キャッシュヒット方式: 共通レビュー仕様を不変の接頭辞として先頭に置き、可変部を末尾に置く。
  DSH は SDK JSON-RPC の常駐プロセス 1 セッションで複数レビューを処理する。Agy は --continue で
  同一会話を再開する。
- 完全 Go が出るまで先へ進めない。条件付き Go は不採用。
- UI は二重実装し、ユーザーが比較して採用を決める。

## 15. リスク

- R1 終端 exact の再生互換が不十分な可能性 → 検証し、必要なら既定を keyframeBefore に変更。
- R2 キーフレーム間隔が粗いと開始の誤差が最大 1 GOP → UI 明示とスマートカット v1.1。
- R3 長尺 4K の索引・プロキシ生成が遅い → バックグラウンドと進捗。
- R4 HDR/10bit の LUT と色変換の正しさ → v1 は LUT のみ、プレビューはトーンマップ。
- R5 モバイル Safari の再生制約 → ユーザー操作起点の再生とプロキシ。
- R6 出力コンテナ互換 → 対応表・除外・MKV remux 提案。
- R7 ffmpeg のライセンスと取得元 → 固定版とハッシュ、README 明記。
- R8 ローカル Qwen の UI 品質・コンテキスト長 → 採用はユーザー判断。API 契約を固定して比較。

## 16. 受け入れ基準

- A1 無変換: H.264/AAC MP4 と H.265 MKV で、コピー区間のハッシュ列がソースと一致。
- A2 目的時刻と実カット区間の差が UI に表示され、inSnap/outMode の定義どおり。
- A3 モバイル実機で、PC 上の非対応コーデック動画をプロキシ再生・コマ送りできる。
- A4 時間入力・シーク・コマ送りで IN/OUT を設定でき、出力に反映される。
- A5 出力先の既定が仕様どおり（PC ソースは元フォルダ、アップロードはビデオフォルダ）。
- A6 非プライベート IP からのアクセスが 403、IPv6 ULA は許可、Host 不一致は拒否。
- A7 LUT・スタビライザー・クロップが動作し、非無変換が明示される。
- A8 計画と成果物のレビューで 2 名の完全 Go を取得している。
- A9 UI が本人版と Qwen 版の 2 つ動作し、ユーザーが採用を決定できる。

## 17. レビュー指摘対応表

| 指摘 | 重要度 | 対応 |
|---|---|---|
| agy C1 -map 0 と非互換データ、faststart | Critical | §3.2, §6 |
| agy C2 フィルタの Windows パスと vidstab 整合 | Critical | §7 |
| agy M3 時刻精度・単位 | Major | §3.3, §5 |
| agy M4 終端の未決と framemd5 矛盾 | Major | §3.1, §3.3, §6 |
| agy M5 索引・コマ送りの性能 | Major | §3.6, §5, §13 |
| agy M6 再エンコードの矛盾・10bit H.264・色 | Major | §7 |
| agy M7 セキュリティ（ULA/射影/トークン/Host/media） | Major | §9 |
| agy M8 クリーンアップ・ロック・命名・既知フォルダ | Major | §8, §10 |
| agy m9 直接再生判定 | Minor | §3.4 |
| agy m10 ffmpeg 固定版とハッシュ | Minor | §3.5 |
| GLM M1 終端スナップ方向 | Major | §3.1 |
| GLM M2 ストリーム毎のコピー可否 | Major | §3.2 |
| GLM M3 トークンの主張 | Major | §9 |
| GLM M4 アップロード配信 | Major | §9 |
| GLM m1 faststart | Minor | §6 |
| GLM m2 IPv4 射影・ULA | Minor | §9 |
| GLM m3 Host 許可集合 | Minor | §9 |
| GLM m4 索引取得方法 | Minor | §3.6 |
| GLM m5 framemd5 と make_zero | Minor | §3.3 |
| GLM m6 時刻表現 | Minor | §3.3 |
| GLM m7 tune film と x265 | Minor | §7 |
| GLM m8 mode と options、crop/stab 順 | Minor | §7 |
| GLM m9 HDR/10bit プレビュー | Minor | §3.4 |
| GLM m10 キャッシュ上限と必要容量 | Minor | §10 |
| GLM m11 長パス・非 ASCII | Minor | §10 |
| GLM m12 §4 と §10 の矛盾 | Minor | §4, §11 |
| GLM m13 未定義事項の解消 | Minor | §5, §9, §12 |
