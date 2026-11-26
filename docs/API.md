# Trim API 仕様（UI 契約）

すべて同一オリジン。JSON。時刻の単位は整数マイクロ秒（us）。POST/DELETE はヘッダ X-Trim-Token（strongMode では Cookie）が必要。
アクセス元はプライベート IP（RFC1918 / ULA / リンクローカル / ループバック）と Tailscale の tailnet（100.64.0.0/10、
config の allowTailnet が true のとき）。Host は自分の名前（列挙した自ホスト名・Tailscale 名 *.ts.net）と
自分のアドレス（LAN・Tailscale）のみ許可。

## 基本

- GET /api/health -> {ok, ffmpeg, ffmpegVersion, version, build, ffmpegPath}
- GET /api/token -> {token, strongMode:false}（strongMode では 403 token_disabled。POST /api/auth を使う）
- POST /api/auth {token} -> {ok}（strongMode 用。HttpOnly・SameSite=Strict の Cookie を発行）
- GET /api/config -> {allowedRoots, defaultUploadOutput, videosDir, strongMode, previewMode, defaultUi, maxUploadBytes}
- GET /api/roots -> {roots:[{path,name,exists}]}
- GET /api/browse?path=&limit=300&offset=0 -> {path,parent,entries:[{name,path,dir,size,mtimeMs,ctimeMs}],total,offset,limit,truncated}
  （動画・音声拡張子のみ。showAll は互換引数で現在は未使用。limit は 1..2000 に丸める）
- POST /api/media-dates {paths:[abs,...]} -> {dates:{<path>:{shotAtMs,shotAtRaw}}}（最大200件。失敗は null）
- POST /api/fs/mkdir {path} -> {path}（許可ルート内に1階層だけフォルダを作成）
- POST /api/fs/delete {path} または {paths:[...]} -> {deleted:[{path,bytes}],failed:[{path,error}]}
  （メディア拡張子のみ。最大200件。1件も消せない場合は 400 invalid_path）
- GET /api/fs/download?path=<abs> -> ファイル本体（Content-Disposition: attachment。動画・音声拡張子のみ、
  許可ルート内の既存ファイルのみ。範囲外 400 invalid_path、不存在・フォルダ 404 not_found）
- GET /api/fs/zip?path=<abs>&path=<abs>... -> ZIP（選択ファイルをまとめてダウンロード。最大200件。
  メディア拡張子のみ。1件も入れられない場合は 400 invalid_path）
- POST /api/fs/copy {source,destination} または {sources:[...],destination} -> {jobId}
- POST /api/fs/move {source,destination} または {sources:[...],destination} -> {jobId}
  source/sources・destination は許可ルート内。範囲外 400 invalid_path。destination はフォルダ（既存ファイルなら 400）。
  source が存在しない場合は 404 not_found。source 欠落、同じ場所、フォルダ自身の中、同一フォルダへの移動は 400 invalid_path。
  実行中は /api/jobs/{id} で進捗、POST /api/jobs/{id}/cancel で停止できる。衝突時は -1, -2 … を付けて上書きしない。

## ソース

- POST /api/sources/open {path} -> {source}
- POST /api/sources/upload multipart file -> {source}
- GET /api/sources -> {sources:[source]}
- GET /api/sources/{id} -> {source,directPlayable,variant,proxyReady}（proxyReady=false のまま proxy を要求すると
  /media は 409 proxy_not_ready）
- GET /api/sources/{id}/keyframes -> {state,keyframes:[us]}
- GET /api/sources/{id}/frames?fromUs=&countFrames=&spanUs= -> {frames:[us]}
- GET /api/sources/{id}/frame?tUs=&width= -> JPEG
- GET /api/sources/{id}/media?variant=original|proxy -> Range 対応の映像
- POST /api/sources/{id}/proxy -> {jobId}
- GET /api/sources/{id}/sprite -> JPEG / POST /api/sources/{id}/sprite -> {jobId}
- DELETE /api/sources/{id}?keepUpload= -> {deleted}（元ファイルは削除しない）

## 音声タイミング

- POST /api/audio/sync {sourceId,addedSourceId,startUs?,windowMs?,rangeMs?,windows?} -> {jobId}
  （元音声と追加音声のズレ候補を解析。windowMs 2000..600000、rangeMs 100..30000、windows 1..5）
- POST /api/preview/build {sourceId,variant,audioMode,audioShiftMs,addedShiftMs,addedStartMs,addedSourceId} ->
  {url} または {jobId}。プロキシ未生成なら 409 {proxyJobId}（プロキシ完了後に同じ本文で再 POST する二段階）。
  audioMode は original/added/bothTracks/bothMix/mute。audioShiftMs/addedShiftMs/addedStartMs は
  書き出しと同じ整数 ms 契約（非数値は 400 invalid_shift、ずらし量に実用上限なし）。addedStartMs は 0 以上。
  **プレビューは常に1本の焼き込み音声**（両方/同時もミックス）。addedStartMs は追加ファイル内の
  PTS 基準スキップで、start_time が 0 でない場合は指定値から start_time を差し引いた位置が実際の先頭。
  追加音声モードで音声のない追加ソースは 400 invalid_audio。original/mute では addedSourceId を無視する。
- GET /api/preview/media/{key} -> Range 対応の焼き込み済み MP4

## 書き出し

- POST /api/exports {sourceId,startUs,endUs,mode,options} -> {jobId}
  - mode: lossless（既定）| reencode。**reencode では追加音声（added/bothTracks/bothMix）は利用不可**で、
    API は 400 invalid_request「再エンコードでは追加音声を利用できません（無変換を選ぶか、音声モードを元のみ/消音にしてください）」を返す。
  - options: {inSnap:prev|next, outMode:exact|keyframeBefore|keyframeAfter, lut, stabilize, crop:{w,h,x,y},
    order, encoder, audioReencode, videoBitrate, audioBitrate, outputPath, container}
  - audioMode / audioShiftMs / addedShiftMs / addedStartMs / addedSourceId / addedReencode: 音声タイミング
    （docs/PLAN_AUDIO_EXPORT.md）。**addedStartMs は追加ファイル内の開始位置（0以上、負値は 400 invalid_shift）**。
    切り出しは音声ストリームの PTS 基準で、start_time が 0 でない場合は指定値から start_time を差し引いた位置が実際の先頭。
  - delayNoReencode: true|false（既定 false、他の型・値は 400）。区間先頭に余裕がない正のずらしで、
    音声を再エンコードせずコンテナの開始位置で遅らせる。開始位置を無視する再生アプリでは反映されない。
    この経路はチャプターを出力しない。
  - videoBitrate/audioBitrate: kbps（未指定は CRF / 元ビットレート）。非数値・0以下は 400 invalid_bitrate。
  - startUs/endUs が整数でない場合や本文が不正な JSON は 400 invalid_request。
- 再エンコード音声のコーデックはコンテナ別（mp4系=aac、ogg/webm=libopus、asf=wmav2、mp3=libmp3lame、
  avi/flv=libmp3lame、mpeg=mp2、wav/aiff=pcm_s16le、flac=flac）。wmav2/libmp3lame/mp2 は2chまで（3ch以上は 400 invalid_container）。
- container: 未指定は自動。指定可能な値は mp4/mov/matroska/webm/ipod/mp3/adts/wav/flac/ogg/asf/aiff/mxf/mpeg/avi/flv のみ
  （"rm" は不可。.rm/.rmvb は自動で MKV）。未知の値・格納できない組み合わせ・単一音声コンテナへの音声1本以外は
  400 invalid_container。
- export result: {outputPath,bytes,actualStartUs,actualEndUs,container,note,excluded,lossless,warnings,fallback,audio}
  - **audio**: {mode,origShiftUs,addedShiftUs,addedStartUs,delayMode,audioReencoded,addedReencoded,headSkipUs,
    addedStartTooLong,...}（音声を実際にどう処理したかの記録。delayMode は元音声トラックの方式で、
    "none"/"adelay"/"timestamp"。追加音声側は addedShiftUs/addedReencoded 等で確認する）
  - warnings には音声のフォールバック、出力先変更などの通知が入る。

## ジョブ・その他

- GET /api/jobs?history=20 -> {jobs:[job]}（メモリ上の実行中ジョブ＋SQLite の直近履歴。同一IDはメモリ優先）
- GET /api/jobs/{id} -> {job}（メモリに無ければ永続化履歴。persisted=true。どちらにも無ければ 404）
- GET /api/jobs/{id}/events -> SSE（event: state / log / done、data は JSON）
- POST /api/jobs/{id}/cancel -> {cancelling}
- GET /api/luts -> {luts:[{name,path}],dir}
- POST /api/luts/dir {path} -> {dir,luts}（LUT フォルダを変更して config.json に保存）
- POST /api/luts/reveal -> {dir}（PC のファイルマネージャで LUT フォルダを開く）
- POST /api/luts/upload multipart file -> {dir,luts,saved}（.cube/.3dl/.dat、上限あり）
- POST /api/paths/validate {path,sourceId?,startUs?,endUs?} -> {writable,reason,freeBytes,estimatedNeedBytes,pathLength,path}
- GET /compare -> 比較用 HTML（開発用）

## オブジェクト

source: {id,kind,name,path,origin,container,durationUs,size,width,height,fps,videoCodec,audioCodec,pixFmt,
indexState,bitRate,videoBitRate,audioBitRate,meta,streams,shotAtMs,shotAtRaw,fileCtimeMs,fileMtimeMs}
bitRate/videoBitRate/audioBitRate: bps（不明なら null）。kind: "video" | "audio" | "other"。
streams[i]: {index,type,codec,codec_long_name,profile,level,width,height,pix_fmt,color_space,color_transfer,
color_primaries,bits_per_raw_sample,avg_frame_rate,r_frame_rate,field_order,bit_rate,nb_frames,duration_us,
sample_rate,channels,channel_layout,attached_pic,default,forced,tags}
job: {id,kind,sourceId,sourceName,status,progress,message,result,error}（永続化由来は persisted:true。
kind: export / proxy / sprite / index / copy / move / preview / audio_sync）
export の result は上記。copy/move の result は {outputPath,moved,bytes}。

対応拡張子: 動画 mp4/m4v/mov/mkv/webm/avi/wmv/flv/ts/m2ts/mts/m2t/mpg/mpeg/3gp/3g2/ogv/lrv/insv/insp/360/mxf/dv/vob/rm/rmvb/f4v/mod/tod、
音声 mp3/m4a/aac/wav/flac/ogg/oga/opus/wma/aif/aiff。
※ .lrv/.insv/.insp/.360/.3g2 は MP4 内容（出力は MP4。.insp は静止画で1フレーム扱い）、.f4v は FLV、
.mxf は MXF（PCM 以外の XAVC 系は MKV に退避）、.dv は AVI、.vob/.mod/.tod は MPEG-PS、.rm/.rmvb は MKV に出力。
※ 出力ファイル名が既存と被る場合は自動で -1, -2 … と連番（上書きしない）。

## 静的マウント

- / -> TrimStudio UI（web-qwen）
- /web -> 旧 UI
- /qwen -> TrimStudio UI（旧リンク互換）
