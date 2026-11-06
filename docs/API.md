# Trim API 仕様（UI 契約）

すべて同一オリジン。JSON。時刻の単位は整数マイクロ秒（us）。POST/DELETE はヘッダ X-Trim-Token（strongMode では Cookie）が必要。 アクセス元はプライベート IP（RFC1918 / ULA / リンクローカル / ループバック）と Tailscale の tailnet（100.64.0.0/10、config の allowTailnet が true のとき）。Host は自分の名前（列挙した自ホスト名・Tailscale 名 *.ts.net）と自分のアドレス（LAN・Tailscale）のみ許可。

- GET /api/health -> {ok, ffmpeg, ffmpegVersion, version}
- GET /api/token -> {token}（strongMode では 403。POST /api/auth を使う）
- POST /api/auth {token} -> {ok}（strongMode 用。HttpOnly Cookie を発行）
- GET /api/config -> {allowedRoots, defaultUploadOutput, videosDir, strongMode, allowTailnet, previewMode, defaultUi, maxUploadBytes}（videosDir は Windows のビデオフォルダで、動画選択の初期表示に使う）
- GET /api/roots -> {roots:[{path,name,exists}]}
- GET /api/browse?path= -> {path, parent, entries:[{name,path,dir,size}]}（動画・音声拡張子のみ）
- POST /api/fs/mkdir {path} -> {path}（許可ルート内に1階層だけフォルダを作成）
- GET /api/fs/download?path=<abs> -> ファイル本体（Content-Disposition: attachment。**動画・音声拡張子のみ**（その他は 400 invalid_path で内容を返さない）。許可ルート内の既存ファイルのみ。範囲外 400 invalid_path、不存在・フォルダ 404 not_found。日本語名は filename* でエンコード）
- POST /api/fs/copy {source,destination} -> {jobId}（ファイル/フォルダをコピー。非同期ジョブ）
- POST /api/fs/move {source,destination} -> {jobId}（移動。同一ボリュームは rename、跨ボリュームはコピー後に元を削除。非同期ジョブ）
  source/destination はどちらも許可ルート内である必要があり、範囲外は 400 invalid_path。destination はフォルダ（既存ファイルなら 400）。
  source が存在しない場合は 404 not_found。source か destination が欠落、同じ場所、フォルダ自身の中、同一フォルダへの移動は 400 invalid_path。
  実行中は進捗が /api/jobs/{id} で見え、POST /api/jobs/{id}/cancel で停止できる。衝突時は -1, -2 … を付けて上書きしない。
  最終名はサニタイズされます（禁止文字は _ に置換、予約名 CON/NUL/COM1 等は _CON のように前置、末尾の空白とドットは除去、
  ドット入りの名前はそのまま保持）。範囲外・空名は 400 invalid_path、不正 JSON は 400 invalid_request、OS エラーは 400 mkdir_failed。
- POST /api/sources/open {path} -> {source}
- POST /api/sources/upload multipart file -> {source}
- GET /api/sources -> {sources:[source]}
- GET /api/sources/{id} -> {source, directPlayable, variant, proxyReady}（proxyReady はプロキシ実体の有無。false のまま proxy を要求すると /media は 409 proxy_not_ready）
- GET /api/sources/{id}/keyframes -> {state, keyframes:[us]}
- GET /api/sources/{id}/frames?fromUs=&countFrames=&spanUs= -> {frames:[us]}
- GET /api/sources/{id}/media?variant=original|proxy -> Range 対応の映像
- GET /api/sources/{id}/frame?tUs=&width= -> JPEG
- POST /api/sources/{id}/proxy -> {jobId}
- GET /api/sources/{id}/sprite / POST /api/sources/{id}/sprite -> JPEG / {jobId}
- DELETE /api/sources/{id}?keepUpload= -> {deleted}（元ファイルは削除しない）
- POST /api/exports {sourceId,startUs,endUs,mode,options} -> {jobId}
  options: {inSnap:prev|next, outMode:exact|keyframeBefore|keyframeAfter, lut, stabilize, crop:{w,h,x,y}, order, encoder, audioReencode, videoBitrate, audioBitrate, outputPath, container}
  videoBitrate/audioBitrate: kbps。映像は未指定なら CRF、音声は未指定なら元の音声ビットレートを踏襲（不明時 192kbps）。
  非数値・0以下は 400 invalid_bitrate。startUs/endUs が整数でない場合や本文が不正な JSON の場合は 400 invalid_request。
  再エンコード音声のコーデックはコンテナ別（mp4系=aac、ogg/webm=libopus、asf=wmav2、mp3=libmp3lame、avi/flv=libmp3lame、mpeg=mp2、wav/aiff=pcm_s16le、flac=flac）。
  wmav2 / libmp3lame / mp2 を使うコンテナでは音声再エンコードは2チャンネルまでで、3ch 以上は 400 invalid_container。
  container: 未指定なら自動選択。指定可能な値は mp4 / mov / matroska / webm / ipod / mp3 / adts / wav / flac / ogg / asf / aiff / mxf / mpeg / avi / flv（16種） のみ（"rm" は指定不可。拡張子 .rm/.rmvb のソースは自動で MKV に退避）。
  未知の値、格納できないストリーム、単一音声コンテナ（mp3/adts/wav/flac/aiff）への音声1本以外の指定は、ジョブを作成せず 400 invalid_container を返す。
- GET /api/jobs?history=20 -> {jobs:[job]}（実行中メモリ上のジョブ＋SQLite に永続化された直近ジョブ。同一 ID はメモリ優先）
- GET /api/jobs/{id} -> {job}（メモリに無ければ永続化された履歴を返す。persisted=true が付く。どちらにも無ければ 404）
- GET /api/jobs/{id}/events -> SSE（event: state / log / done、data は JSON）
- POST /api/jobs/{id}/cancel -> {cancelling}
- GET /api/luts -> {luts:[{name,path}]}
- POST /api/paths/validate {path,sourceId?,startUs?,endUs?} -> {writable,reason,freeBytes,estimatedNeedBytes,pathLength,path}

source: {id,kind,name,path,origin,container,durationUs,size,width,height,fps,videoCodec,audioCodec,pixFmt,indexState,bitRate,videoBitRate,audioBitRate,meta,streams}
bitRate/videoBitRate/audioBitRate: bps（不明なら null）。meta: {format_name,format_long_name,nb_streams,bit_rate,start_time,probe_score,tags}
streams[i]: {index,type,codec,codec_long_name,profile,level,width,height,pix_fmt,color_space,color_transfer,color_primaries,bits_per_raw_sample,avg_frame_rate,r_frame_rate,field_order,bit_rate,nb_frames,duration_us,sample_rate,channels,channel_layout,attached_pic,default,forced,tags}
kind: "video" | "audio" | "other"。音声のみのソースは kind=audio、keyframes は空で state=ready、/frame は 404。

対応拡張子: 動画 mp4/m4v/mov/mkv/webm/avi/wmv/flv/ts/m2ts/mts/m2t/mpg/mpeg/3gp/3g2/ogv/lrv/insv/insp/360/mxf/dv/vob/rm/rmvb/f4v/mod/tod、音声 mp3/m4a/aac/wav/flac/ogg/oga/opus/wma/aif/aiff
  ※ .lrv/.insv/.insp/.360/.3g2 は MP4 内容（出力は MP4。ただし .insp は静止画で1フレーム扱い）、.f4v は FLV、.mxf は MXF（音声が PCM 以外の XAVC 系は MKV に退避）、.dv は AVI、.vob/.mod/.tod は MPEG-PS、.rm/.rmvb は MKV に出力されます（いずれもパケットコピー）。
  ※ 出力ファイル名が既存と被る場合は自動で -1, -2 … と連番を付けます（上書きしません）。ソースの表示名も同名なら連番になります。
音声コンテナ: mp3 / ipod(m4a) / adts(aac) / wav / flac / ogg / asf(wma) / aiff（FLAC のみ可逆再エンコードで STREAMINFO を補正）
job: {id,kind,sourceId,sourceName,status,progress,message,result,error}（sourceName は登録済みソースの表示名。永続化由来は persisted:true が付く。error も DB に保存され再起動後も参照できる）
  kind: export / proxy / sprite / index / copy / move。copy・move の result は {outputPath,moved,bytes}。
export result: {outputPath,bytes,actualStartUs,actualEndUs,container,note,excluded,lossless,warnings,fallback}
  warnings には「既定の出力先が書き込めないため <dir> に変更しました」等のフォールバック通知が入る。
  未指定の出力先が書き込めない場合は ビデオフォルダ → data/exports の順に書き込める場所へ自動で変更する（明示指定時はエラー）。
note: FLAC 出力時の「可逆再エンコード（STREAMINFO 補正）」など、無変換コピー以外の補足。
