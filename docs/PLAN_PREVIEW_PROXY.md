# 計画: プレビューを「書き出しパイプラインで生成したプロキシ」へ置き換える（v3.1）

対象: L:/dev/Trim / 作成: 2026-11-10 / 状態: 計画確定（実装移行待ち）

## 0. 改訂履歴

| 版 | 変更 |
|---|---|
| v0.1 | 初版 |
| v0.2 | Agy Critical（iOS自動再生）／Qwen Critical（音声仕様欠落）を反映 |
| v0.3 | 第1ラウンド全指摘を反映（音声のみ・トリム維持・書き出不変の根拠・.part・apad・variant/認証・Windows・両トラック検証・既存プロキシ流儀） |
| v0.4 | 第2ラウンド全指摘を反映。(1) **シフト基準を「映像内容」と定義**しトリムとの整合を証明（GLM M-1）。(2) **切り詰めと無音伸長を全モード共通段に統一**（Agy M-1/GLM m-1）。(3) **cacheKey に variant 実体の size/mtime** を追加（Agy M-2/GLM m-2）。(4) **尺 D を厳密定義**（Agy M-3/Qwen M-3）。(5) **音声フィルタ構築を書き出しと共通関数化**（Qwen M-2）。(6) Windows 長パス/非ASCII を明記（Qwen M-1）。(7) 音声なし素材・多音声選択・addedReencode（Qwen M-4/GLM m-3/m-4）。(8) framemd5 による映像同一性検証（GLM m-5）。(9) 移行で shift 値を**破棄せず**保持（GLM m-6）。(10) 静的ガードを機械判定可能な形に（GLM m-7）。(11) 同時実行は既存ジョブ上限に従う（GLM m-8）。 |
| v0.5 | 第3ラウンド全指摘を反映（定型の改訂行は下記）。映像入力をvariant・音声入力を常にオリジナルに分離／timingInactive の解除トリガ追加／contentSig・.okマーカー・canonical JSON／variant検証とproxyチェーン／bothTracks→bothMix正規化／容量事前確認／PTS正規化／ジョブtoken・位置復元／読み込み中キーの保護定義／共通後段の抽出前検証／audioTiming ペイロード矛盾の解消。 |
| v0.6 | Qwen R4 Critical を反映: 音声パケットコピー経路（shift=0/MP4互換）・priming補償・timing-referenceモード・時間軸正規化契約（sourceTimelineOffsetUs）・受入13/14。 |
| v0.7 | GLM R4 Major を反映: cacheKey に contentSig を正式フィールド化／timingInactive の解除トリガを3つに統一／映像入力の start_time を `-itsoffset` で原点化（copyでも有効）／framemd5 は内容比較・.ok 競合規則・保護規則の一本化・容量推定式・variant解決後キー・キャンセル経路。Agy R4 Minor（モード相関検証・版数）も反映。 |
| v1.0 | Qwen R6 Major を反映: addedStartMs の配置規則／variant時間軸オフセット／受入2の2系統化／timingInactive の確認。|
| v1.1 | GLM R7 Major を反映: start_time は**ストリーム単位**で取得（videoStart=選択映像ストリーム、audioStart=選択音声ストリーム、sourceTimelineOffsetUs=variant映像ストリーム）。命名を `sourceTimelineOffsetUs` に一本化。D行を §3.3.1 参照に統一。`.ok`/`.json` の掃除と key→メタ索引（サイドカーJSON）を確定。 |
| v1.2 | Qwen R8 Major を反映: 応答に sourceTimelineOffsetUs を必須化、入力番号と -map のモード別表、音声なし＋added の入力構成、負シフトを総遅延 `s+rel` に統一。 |
| v1.3 | Agy R9 Major を反映: 総遅延の単位を秒に明義（tot_sec=(shiftMs/1000)+rel_sec、atrim=start=-tot_sec）／全モードが filter_complex を通ることを明記し -map をラベル出力に統一。 |
| v1.4 | 予備レビュアー Major を反映: **サーバ側チェーン機構を作らない**（クライアント駆動2段階＋`proxyRequired`応答）、**ジョブ優先度機構を作らない**（既存FIFO・キュー表示のみ）、cacheKey は解決後の variant と **解決後の audioMode** を使う。GLM R8 Minor の式矛盾は v1.3 で解消済み。 |
| v1.5 | GLM要約R の Major を反映: 音声入力を `asetpts=PTS-STARTPTS` で原点化してから tot を適用する手順を明記／`-itsoffset`＋`-c:v copy` の妥当性検証（出力 start_time=0・フレーム同一）を受入に追加／copy非対応コーデックのフォールバック、.part掃除タイミング、contentSig注記。 |
| v1.6 | Qwen R11 Major を反映: 保護規則を一本化（GET基準が正・open handle/セッション保護は安全側の追加）／cacheKey に videoStreamIndex、`-itsoffset` は Input0 限定を例示、copy不可時のAPI動作、負start_timeの正規化を明記。 |
| v1.7 | GLM R10/R11 Major を反映: `.json` を `.ok` より先に書き、ヒット判定に `.json` を必須化／`sourceTimelineOffsetUs` は**生成後の実測 start_time** を返す契約（itsoffset不成立でも成立）／負start_timeはクランプせず渡す／D欠損時は映像ストリームで再取得／縮退時レートは added 側固定／`-fflags +genpts` は入力側。 |
| v1.8 | GLM要約R16 Major を反映: 負シフトは `atrim` 後に必ず `asetpts=PTS-STARTPTS`（受入16で出力音声 start_time=0 を検証）／異種フォーマットの `aformat/aresample` 正規化、`adelay:all=1`、ffmpegバージョン要件、フィルタ論理変更時の impl 版数更新を明記。 |
| v1.9 | Agy R12 Major を反映: `aformat/aresample` 正規化を §3.3 表に**具体フィルタとして明記**（amix 各入力段の手前）／§7.1 の負 start_time 記述を §3.3.1 と一致させる（クランプしない・解析不能時のみ0.0・offsetは実測）。 |
| v2.0 | GLM要約R18 Major を反映: variant 解決は **ブラウザ再生可否(direct_playable) と MP4 copy可否の両方**を条件とし、どちらか不可なら proxy（409→2段階）。ヒット判定は mp4+`.json`+`.ok` の3点必須に統一。framemd5はフレーム内容、生成中キー保護、409ポーリング上限を明記。 |
| v2.1 | Qwen R12 Major を反映: 応答を `sourceTimelineOffsetUs`（UI写像用＝variant映像ストリームstart_time）と `outputStartOffsetUs`（実測出力start_time・診断用）に分離して二重定義を解消／負start_timeの矛盾記述を削除／`proxy_required` はサーバがproxyジョブを起動して`proxyJobId` を返す契約に統一。 |
| v2.2 | Agy R13 Major を反映: 409ポーリングのタイムアウト／再送は最大1回でループ抑止を §3.1・§3.6 本文に明記／ヒット判定を §3.2 でも「mp4+json+ok の3点必須」に統一。 |
| v2.3 | GLM要約R20 Major を反映: -itsoffset が copy で無視された場合（outputStartOffsetUs != 0）の**明示的フォールバック**を定義（音声に +S の adelay を追加して再生成→それでも不可なら映像再エンコード）。 |
| v2.4 | Qwen R13 Major を反映: 409 proxy_required 後の **ポーリング上限（120回（1秒間隔・最大120秒））・タイムアウト時の409 proxy_generation_timeout・再送は成功時のみ** を本文/受入に明記。応答の offset 2フィールド化は v2.1 で解消済み。 |
| v2.5 | Agy R14 Major を反映: itsoffset不成立時の**成功判定をA/Vオフセット（実測±5ms/1フレーム）**に修正／§7.1 の記述を2フィールド契約に整合。GLM要約R24 Minor（proxyタイムアウト統一・フォールバック受入・LRU解除・added複数ストリーム）も反映。 |
| v2.6 | Qwen R14 Major を反映: .json サイドカーに**必須スキーマ**を定義／contentSig に ffprobe 署名を加えて中間部変更も検出／409 を proxy_required（初回・proxyJobId付き）と proxy_unavailable（再送不可）に分離して矛盾解消。 |
| v2.7 | Qwen R15 Major を反映: **入力番号は §3.3.2 の表を唯一の定義**とし、§3.1 の「常にInput1/Input2」記述を削除（有効な入力だけを詰める）。409契約を §3.4 に正式追記。 |
| v2.8 | 三者完全Go後のMinor整理: 受入14の欠番を復元し全19項を昇順化／contentSigの主張を「ffprobe署名は補助・主検知は size/mtime/先頭末尾」に弱める／ポーリングを「1秒間隔・最大120回（120秒）」に統一／itsoffset+copyは実質デッドパスである旨を注記。 |
| v2.9 | Qwen R16 Major を反映: §3.4 に**統一された応答スキーマ**（cached/ジョブ完了の双方で sourceTimelineOffsetUs + outputStartOffsetUs）／LRU保護を build成功時登録＋GETでTTL更新＋明示解除へ強化。 |
| v3.0 | Qwen R17 Minor: §3.4 の応答スキーマ重複記載を削除（冒頭一覧のみが正）／受入IDを昇順に整列。 |
| v3.1 | 実装検証で判明: -avoid_negative_ts make_zero は映像copyのPTSを約66msずらして start_time≠0 を生むため使用しない（入力側 -fflags +genpts、出力 start_time=0 を検証）。 |

## 1. 背景と問題

現行プレビューは `<video>` と別 `<audio>` の2要素を同時再生し、`currentTime` を毎フレーム補正している。

症状:
- (a) **iPhone のみ**音声が断続・停止。Android では起きない。
- (b) プレビューと書き出しで「合う値」が一致しない（実測: プレビュー +100ms / 書き出し +500ms）。

原因（測定済み）:
- **書き出しの音声遅延は要求どおり正しく適用されている**。相互相関で「要求+1000ms → +884ms」と出たのは測定基準がカット開始点（0.1167s）だったための参照誤差で、ファイル内の相対遅延は 1000ms ちょうど。**書き出し側の修正は不要**（＝受入基準5と矛盾しない）。
- ズレの実体は**旧プレビュー**。別要素の音声はバッファリング開始が遅れ約400ms後ろに居座り、旧実装の不感帯がそれを放置したため「プレビュー+100 ≒ 書き出し+500」になった。
- 補正のためのシークはバッファを捨てて再取得させるため「遅れ→補正→また遅れ」のループになり、これが断続音。
- iOS Safari は同時再生の制限が強く、2要素方式が成立しない。

結論: 2要素方式をやめ、**単一の `<video>` で「音声タイミングを焼き込んだ MP4」を再生する**。

## 2. 決定事項（ユーザー確定）

- 秒数指定UI（数値入力・ジョグ・±msボタン）は**現状のまま維持**。値は書き出し／プロキシ生成の設定値。
- **即時反映機能は削除**。
- **「プレビューに反映」ボタン**を追加し、押すとプロキシを生成して読み込む。
- 生成範囲は**動画全体**。
- **映像エフェクト（LUT・スタビライザー・クロップ等）はプレビューに反映しない**（既存プロキシも同様）。本プロキシは**音声タイミング確認用**。UI ラベルもその旨。
- サイズ・時間の**上限は設けない**（既存プロキシと同じ）。空き容量の事前確認・進捗・キャンセルは付ける。

## 3. 設計

### 3.0 シフトの基準（トリムとの整合）

シフトは**「映像内容」に対する音声内容の相対位置**と定義する（リカバリ経路の検証は受入19）。

- 書き出し（範囲 [IN, OUT]）: 出力時刻 τ の映像内容 = ソース(IN+τ)。正シフト s の音声内容 = ソース(IN+τ−s)。**音声内容 = 映像内容 − s**。負シフト |s| なら 音声内容 = 映像内容 + |s|。
- 全体プレビュー: 時刻 τ' の映像内容 = ソース(τ')、音声内容 = ソース(τ'−s)。**同じ関係式**。
- したがって**トリムを変えてもプレビューは再生成不要**で、書き出しと一致する。唯一の例外はソース先頭付近（τ<|s|）で、正シフトは両者とも先頭が無音にクランプされる（同じ規則）。

### 3.1 生成

- 新ジョブ種別 `preview`。**映像は現在の再生バリアントからコピー**（`-c:v copy`）。時間軸・キーフレーム・尺は元動画と同一で、トリムUIはそのまま使える。
- **variant の決定はサーバ側で検証する**（Qwen R3-3/R3-4 / GLM要約R18 Major）: `variant=original` は **①ブラウザ再生可否（`ffmpeg_tools.direct_playable`）と ②MP4へ `-c:v copy` 可能かの両方**を満たす場合のみ許可する。片方でも不可（HEVC/WebM/VP9 等）なら `proxy` を強制し、proxy 不在なら 409 → 2段階フロー。**「copyはできるがブラウザで再生できない」ケースで黒画面プレビューを出さない**ことを受入17で検証する。
  - **サーバ側のジョブ依存機構は作らない**（予備R Major-1）。proxy 未生成の場合は `409 {code:"proxy_required", proxyJobId:"…"}` を返し、**クライアントが proxy 生成 → 完了待ち → preview を再送**する2段階フローにする（既存のジョブAPI・ポーリングをそのまま使用。デッドロック・依存解決・エラー伝播の新規設計が不要）。
  - **クライアントの復帰フロー（厳密仕様・Qwen R13/R14 Major）**:
    - 初回応答 `409 {code:"proxy_required", proxyJobId}` → その **proxyJobId を1秒間隔・最大30回/120秒**ポーリングする。
    - proxy ジョブが `error`/`cancelled` または上限到達 → **preview は再送しない**。クライアントは「プロキシ生成に失敗/時間切れ」を表示して終了する（この経路でサーバが preview 409 を返す場面は無い）。
    - preview の再送は **proxy ジョブ完了時のみ・最大1回**。再送しても用意できない場合はサーバが `409 {code:"proxy_unavailable"}` を返し、クライアントは**即中止してエラー表示**（無限再送の禁止）。
  - copy不可（VP9/MKV等）の場合は **variant=proxy に自動解決**し、proxy 不在なら同じ `409 proxy_required` を返す（Qwen R11 Minor）。
  - proxy 生成も不可なら 409＋明示メッセージ（UI も選択不可にする）。
- **注記**: `-itsoffset`＋`-c:v copy` は環境により無視される実質デッドパスであるため、実装コードにその旨を明記し、受入15/19の検証を必ず通す。
- **入力オプションの例**: `ffmpeg -itsoffset -<videoStart> -i <variant> -i <source audio> …`（**-itsoffset は Input0 の -i 直前のみ**。音声入力には掛けない）。
- **入力オプションの配置**: `-itsoffset -<videoStart>` は**対象入力の `-i` の直前**に置く（後ろに置くと無効。Agy R11-1）。
- **入力は映像と音声で分離する**（Agy R3-1）:
  - **映像入力（Input 0）**: `variant=original` ならソース実体、`variant=proxy` なら既存プロキシ。`-c:v copy`。パスは既存の `long_path()` を通す（Windows 長パス対応）。
  - **音声入力は常にオリジナルソース実体から取得**する（既存プロキシの音声は第1音声のみ・AAC再エンコード済みで、二重エンコードの約20ms遅延や多音声欠落を招くため）。**入力番号は §3.3.2 の表を唯一の定義**とし、有効な入力だけを詰めて構成する。追加音声を使う場合も `long_path()` と許可ルート検証を通す。
- **音声 PTS の正規化**（Qwen R3-7）: 音声 filter の先頭で `asetpts=PTS-STARTPTS` を必須とする（`atrim start` と `adelay` は PTS 原点前提のため）。
- **copy非対応コーデックのフォールバック**: variant がブラウザ再生可能でも MP4 へ `-c:v copy` できない場合（VP9/MKV 等）は、既存プロキシ生成（H.264）へフォールバックする。
- **`.part` の掃除タイミング**: ジョブ開始時に1時間超の古い `.part` を掃除し、キャンセル・失敗時は即時削除する。
- **contentSig の mtime 依存**: ファイルコピー等で mtime が変わるとキャッシュミスが増えるが、誤ヒットより安全側なので許容（注記）。
- **ffmpeg バージョン要件**: `amix=normalize=0` は ffmpeg 5.1 以降。同梱は 9.0.2 で問題なし（起動時に版数をログ）。
- **フィルタ論理を変更したら cacheKey の `impl` を必ず更新**する（旧キャッシュの誤ヒット防止）。
- **実行規約**: ffmpeg は**引数リスト + shell=False** で起動する（既存踏襲、コマンド文字列連結は禁止）。**出力パスも `long_path()` を通す**（Windows 長パス・非ASCII対策）。
- **再生中の LRU 保護**（Qwen R5-minor）: 再生中は Range GET が継続するため、§3.2 の「GET 成功から activeWindowSeconds 以内」規則で自動的に保護される。長尺再生で GET 間隔が空く場合は activeWindowSeconds(600s) が十分に大きいことを明記）。
- 音声: **書き出しと同じ関数**で filter graph を構築する（§3.3）。ワーク用の出力パスは ASCII（`work/preview/<hex>.mp4`）に固定し、非ASCII名を避ける。
- 出力は `<work>/preview/<cacheKey>.mp4`。**`.part` に書き、成功後にアトミック rename**。失敗・キャンセル時は `.part` を削除。**成功時は同名の `<cacheKey>.json`（キー→メタ索引）を書いてから `<cacheKey>.ok` マーカーを書く**（この順序を固定。GLM R10 M-1）。rename完了〜マーカー書き込みの競合に備え、**ヒット判定は `<key>.mp4` + `<key>.json` + `<key>.ok` の3点すべてを必須**とし、いずれか欠ければ miss として生成ジョブへ回す（GLM R10 M-1 / 要約R18）。
- **容量の事前確認**（Qwen R3-6）: 推定式は `映像ビットレート×D + 128kbps×D + コンテナオーバーヘッド(約1%)`。生成前に推定サイズを出し、`work/preview` 合計が `workCacheBytes` と空き容量の両方に収まらない場合は 409 で明示的に断る（勝手に落とさない）。使用中キーは LRU 保護。
- **優先度機構は作らない**（予備R Major-2）: 既存の FIFO キューと `jobConcurrency` をそのまま使う。UI には「キュー待ち」を表示し、実行中はキャンセル可能とする（新しい優先度実装は行わない）。
- **キャンセル**: 既存ジョブ機構のキャンセル経路で ffmpeg を停止し、ジョブ状態を `cancelled` にして `.part` を削除する。
- 同一キーの同時生成は排他（実行中キーを保持）。**異なるキーは既存のジョブ同時実行上限（`jobConcurrency`=2）に従う**。
- 進捗: ffmpeg の progress 出力。copy のみの区間は尺ベース推定。
- 音声ストリームが無い素材: **音声トラックなしのプロキシ**を生成するのは「元素材に音声が無く、かつ有効な追加音声も無い」場合に限る。`audioMode=added` 等で追加音声がある場合は追加音声をエンコードして載せる（Agy R3-3）。
- 多音声素材: **書き出しと同一の音声ストリーム選択規則**（`decide_streams`/`_audio_plan`）を再利用する。

### 3.2 キャッシュと削除ルール

- `cacheKey = sha1(json({
    impl:"preview-v2", sourceId, sourceContentSig, sourceSize, sourceMtimeUs,
    variant, variantContentSig, variantSize, variantMtimeUs, videoStreamIndex,
    audioStreamIndex, audioMode, origShiftMs, addedShiftMs, addedStartMs,
    addedSourceId, addedSourceContentSig, addedSourceSize, addedSourceMtimeUs,
    addedAudioStreamIndex
  }))`
  - **`variant` 実体（original=ソース、proxy=既存プロキシ）の size/mtime を含める**ため、既存プロキシを再生成しても stale hit しない。
  - **映像エフェクト設定は意図的に含めない**（プレビューに反映しないため。UIに明記）。
  - `addedReencode` はプレビューでは意味を持たない（常にAAC再エンコード）ためキーに含めない。
- **`sourceContentSig` / `variantContentSig` を cacheKey JSON の正式フィールドとして含める**（GLM R4 M-1）。定義は `sha1(size + mtime + 先頭64KB + 末尾64KB + ffprobe署名(duration, nb_frames, bit_rate, codec, sample_rate))`。ffprobe署名は**補助的な検知**であり、主検知は size/mtime/先頭末尾ハッシュ（中間部のみの改変は理論上の限界として注記）。計算結果は (sourceId,size,mtime) をキーにメモリ/DBへキャッシュして毎回の ffprobe を避ける。DB に内容ハッシュがある場合は**キー生成時にそちらを優先**する（ヒット時検証ではなくキー自体に反映）。
- **JSON は canonical**（キー固定順／`sort_keys` 相当）でシリアライズする（Qwen m-1）。
- **`<key>.json` の必須スキーマ**: `{cacheKey, impl, sourceId, variant, sourceTimelineOffsetUs, outputStartOffsetUs, audioMode, origShiftMs, addedShiftMs, addedStartMs, D, videoStreamIndex, audioStreamIndex, probe:{codec, sampleRate, channels, duration, nbFrames}}`。**いずれかのフィールド欠如は miss 扱い**（ffprobe で再導出して書き戻してから返してよい）。
- **ヒット判定は `<key>.mp4` + `<key>.json` + `<key>.ok` の3点すべてを必須**とし、サイズ>0 も確認する。いずれか欠ければ miss として生成ジョブへ回す（§3.1 と同一規則。Agy R13 Major-2 / Qwen R3-2）。

削除ルール（既存 `cleanup` に統合）:
- `cleanup.enforce` の候補に `work/preview/*.mp4` を追加（上限 `workCacheBytes`＝既定20GBと空き容量10%の小さい方、直近 `activeWindowSeconds`=600秒アクセスのソースと queued/running ジョブのソースは保護、mtime 古い順）。
- **実行中ジョブのキー**と**現在ブラウザに読み込まれているキー**は保護集合に追加（**正判定は「`/api/preview/media/<key>` の GET 成功から `activeWindowSeconds` 以内」**とし、**保護は必須要件**（Qwen R16 Major-2）: ①build成功時に対象キーを保護集合へ登録、②`/api/preview/media/<key>` の GET 成功でTTL更新、③「元に戻る」/ページ離脱で明示解除、④open handle は常に保護。TTL は 600秒を下限とし GET が続く限り延長する。
- `delete_source` で当該ソース由来の preview を削除。**キー→メタの索引はサイドカー JSON（`<key>.json`）**とし、mp4／`.ok`／`.json` を**同一単位で削除**する（`remove_orphans` と LRU の双方で3点セットを対象にする）。
- Windows で再生中ファイルの削除失敗は `except OSError` で握りつぶし次回に回す（既存踏襲）。
- 起動時の `remove_orphans` が `*.part` を1時間で掃除（既存規則）。

### 3.3 音声処理（書き出しと共通化）

**音声は常に AAC-LC へ再エンコード**（シフト/ミックス/ミュートの時点でパケットコピーは不可能）。`addedReencode` の有無に関わらずプレビューは常に再エンコード。

| 項目 | 仕様 |
|---|---|
| codec | AAC-LC（`REENCODE_AUDIO_CODECS` と同じ規則） |
| sample rate | 元音声の sample rate（44100/48000）。不明時 48000。**bothMix は orig 側のレートに固定**（自動ネゴに任せない＝書き出しと一致） |
| channel | 元音声の ch layout。3ch以上は stereo downmix |
| **異種フォーマットの正規化** | オリジナルと追加音声で sample rate / ch layout が異なる場合、**amix の各入力段の手前に** `aresample=<orig_rate>` と `aformat=sample_fmts=fltp:sample_rates=<orig_rate>:channel_layouts=stereo` を挿入し、**orig 側のレート/レイアウトに統一してから** amix に渡す（縮退時は added 側）。単体テストで生成フィルタ文字列を固定する |
| bitrate | 128k（`_audio_bitrate` を再利用） |
| **尺 D** | **プレビューにコピーする映像ストリームの、出力タイムライン上での再生継続時間（秒）**。ffprobe の `streams[v].duration` を優先し、**無ければ `-select_streams v` で映像ストリームに限定して再取得**（`format.duration` は最終手段）。**正規化は §3.3.1 の手順に一元化**し、D はその正規化後の映像尺とする（別機構を併記しない） |
| シフト適用（正負共通） | **単位は秒で統一**。`tot_sec = (要求シフトMs / 1000.0) + rel_sec`（rel_sec は ffprobe の start_time 差分＝秒）。`tot_sec >= 0` なら `adelay=<round(tot_sec*1000)>:all=1`、`tot_sec < 0` なら `atrim=start=<-tot_sec>,asetpts=PTS-STARTPTS`（1000 で割らない）。Qwen R8-4 / Agy R9-1 |
| bothMix | 入力ごとに `_mix_filter` → `amix=inputs=2:normalize=0:duration=longest` |
| **共通の後段（全モード必須）** | **`apad=whole_dur=<D>,atrim=end=<D>,asetpts=PTS-STARTPTS`** → 尺を D に一致させる（短ければ無音で埋め、長ければ切る）。**引数なしの `apad` は禁止**（無限伸長） |
| bothTracks | プレビューでは **`bothMix` に正規化**して同じ関数に渡す（Qwen R3-5）。この対応表を単体テストで固定し、filter 一致テストは「正規化後の入力に対する出力」で比較する |
| mute | 音声ストリームなし |
| シフトが尺以上 | 全区間無音＋警告（書き出し側の既存規則と同じ） |
| コンテナ | MP4 / `-movflags +faststart` |
| 実装境界 | `exports` の音声 filter graph 構築を**共通関数へ抽出**し、書き出しとプレビューの双方が同じ関数を呼ぶ。単体テストで**モード別に生成される filter 文字列の一致**を検証 |
| **音声出力の一致（プリミング込み）** | **プレビューは常に AAC-LC 再エンコード**（パケットコピー経路は設けない。Agy R5-2: copy は filter graph を通せず、尺D一致・PTS正規化が実行できないため）。**エンコーダ遅延・priming/edit list** は `-movflags +faststart` と MP4 edit list で補償する。受入は「映像内容を基準にした A/V オフセットの差」を相互相関で測り、**プリミング補償後 ±5ms**。比較用に、書き出し側も同一 AAC 条件で出力する **timing-reference モード**を用意し、通常のパケットコピー書き出しと直接比較できないケースを検証する |

### 3.3.1 時間軸（start_time/edit list）の正規化契約

- **正規化（具体手順）**（GLM R4 M-3 / Agy R5-1）:
  0. **variant とソースの時間軸対応を先に確定**（Qwen R6-2 / GLM R7 M-1）: **すべてストリーム単位**で取得する。`videoStart` = **variant 入力の選択映像ストリーム**の start_time（最小PTS）、`audioStart` = **ソースの選択音声ストリーム**の start_time。`rel = audioStart − videoStart`。**format.start_time は使わない**（全ストリームの最小値であり、映像0.5s／音声0s のような素材で本来のA/Vオフセットを失うため）。build 応答は `sourceTimelineOffsetUs`（variant 映像ストリームの start_time）と `outputStartOffsetUs`（実測）の2フィールドを持つ（`variantTimelineOffsetUs` という別名は用いない）。variant とソースの時間軸一致は ffprobe テストで 1 フレーム以内を検証する。
  1. ffprobe で `videoStart`（variant）と `audioStart`（ソース）を取得する。
  2. **映像**: `-itsoffset -<videoStart>` で PTS 原点を 0 に揃える（`-c:v copy` でも有効）。
  3. **音声**（単位は秒）: **必ず最初に `asetpts=PTS-STARTPTS` で音声入力を原点化する**（これを飛ばすと adelay/atrim の基準がずれる。GLM要約R Major-1）。その上で rel を遅延として加算する。ここで**元の A/V 相対オフセットを復元する**ため、`rel = audioStart − videoStart` を算出し、**音声の総遅延 = 要求シフト + rel** として適用する（総遅延 > 0 は `adelay`、< 0 は `atrim`）。これにより「素材本来の同期関係」を保ったまま要求シフトだけを加える。
  4. **D は「両入力の正規化後に確定した映像尺」**と定義する（「等で正規化」の曖昧表現は用いない）。
- **クライアントへの契約（2フィールドに分離）**（Qwen R12 Major-1）:
  - `sourceTimelineOffsetUs` = **variant の選択映像ストリームの presentation start_time**。**UI の時刻写像はこれのみを使う**（previewTime = sourceTime − sourceTimelineOffsetUs）。
  - `outputStartOffsetUs` = **生成後の出力を ffprobe で実測した start_time**（**診断用**。正規化成功なら 0）。UI 写像には使わない。
  - 受入15は「itsoffset 不成立時も outputStartOffsetUs を記録し、sourceTimelineOffsetUs による写像で受入14を満たす」と定義する。
- **itsoffset 不成立時の明示的フォールバック**（GLM要約R20 Major）: 生成後に outputStartOffsetUs を測り、**映像がcopyのままだと start_time は S のままなので、成功判定は「出力の実測A/V開始差 |audioStart−videoStart| が ±5ms または1フレーム以内」**とする（outputStartOffsetUs==0 を成功条件にしない）。次の順でリカバリする。
  1. 音声の総遅延に **+S（=outputStartOffsetUs）を加算**して1回だけ再生成する。
  2. それでも許容外の場合は **映像を再エンコード**（既存プロキシ生成経由）へフォールバックする。
  3. いずれも失敗したらジョブを error とし UI に明示メッセージを出す。
  4. フォールバック経路も**受入19**で「音声位置±5ms・A/V同期成立」を検証する。
- **負の start_time はクランプしない**（GLM R11 M-2）: そのまま `-itsoffset` に渡す。ffprobe 値が N/A／欠損で解析不能な場合のみ 0.0 とし、その場合も `outputStartOffsetUs` を記録し、`sourceTimelineOffsetUs` による写像で契約を満たす。UI は「ソース時刻 → プレビュー時刻 = ソース時刻 − sourceTimelineOffsetUs」で写像し、シーク・時間入力・コマ送り・IN/OUT を**同一に扱う**。
- **検証**: start_time≠0／edit list 付き MOV／Bフレーム由来の負PTS の素材で、ソース時刻とプレビュー時刻の対応を 1 フレーム以内で確認するテストを追加する。

### 3.3.2 入力構成と -map（モード別）

入力番号は**有効な入力だけを詰めて**構成し、`-map` を明示する（既定選択に任せない）。

全モードで音声は filter_complex を通す（PTS正規化・シフト・尺D固定のため）。したがって音声のマッピングはフィルタのラベル出力を指定する（入力直結の `-map 1:a:<sel>` は不可。Agy R9-2）。

| mode | 入力構成 | 出力マッピング |
|---|---|---|
| mute | 0=variant映像 | `-map 0:v:0` + `-an` |
| original（元素材に音声あり） | 0=variant映像, 1=ソース音声 | `-map 0:v:0 -map "[aout]"` |
| original（元素材に音声なし） | 0=variant映像のみ | `-map 0:v:0` + `-an` |
| added | 0=variant映像, 1=addedSource音声 | `-map 0:v:0 -map "[aout]"` |
| bothMix / bothTracks（両方あり） | 0=variant映像, 1=ソース音声, 2=added音声 | `-map 0:v:0 -map "[aout]"`（amix 出力） |
| bothMix / bothTracks（元素材に音声なし） | 0=variant映像, 1=added音声 | `-map 0:v:0 -map "[aout]"`（added 単独へ縮退。§7.1） |

**Input1（ソース音声）は「元素材に選択音声がある場合のみ」加える**（Qwen R8-3）。音声なし素材では映像と追加音声だけを入力にし、番号を詰め直す。

### 3.4 API

- **`POST /api/preview/build` の応答スキーマ（統一）**（Qwen R15/R16 Major-1）:
  - キャッシュヒット: `{ok:true, cached:true, url:"/api/preview/media/<key>.mp4", sourceTimelineOffsetUs:<int>, outputStartOffsetUs:<int>}`
  - 生成ジョブ完了結果: `{ok:true, jobId:"...", url:"...", sourceTimelineOffsetUs:<int>, outputStartOffsetUs:<int>}`（ヒットと同一形状）
  - 生成受付: `{ok:true, jobId:"..."}`
  - 要プロキシ: **HTTP 409** `{ok:false, code:"proxy_required", proxyJobId:"..."}`
  - 再送不可: **HTTP 409** `{ok:false, code:"proxy_unavailable"}`
- `POST /api/preview/build` body: `{sourceId, variant, audioMode, origShiftMs, addedShiftMs, addedStartMs, addedSourceId}`
  - ヒット: `{ok:true, cached:true, url:"/api/preview/media/<key>.mp4", sourceTimelineOffsetUs:<int>}`
  - 生成: `{ok:true, jobId:"..."}`。**ジョブ完了結果にも `sourceTimelineOffsetUs` を必須で含める**（Qwen R8-1: キャッシュ／生成の両経路でクライアントが同じ契約を使えるようにする）
- `GET /api/preview/media/<key>.mp4`: 既存 `range_response` を再利用。**`<key>` は `^[0-9a-f]{40}$` のみ受理**。既存の認証/IP検査ミドルウェアを必ず通す。
- **動画ストリーム選択規則**: 常に primary（先頭の映像ストリーム）を使い、`videoStreamIndex=0` を cacheKey に含める（多映像素材でも選択が一意になる。Qwen R11 Minor）。
- `variant` は必須。許可値 `original` / `proxy`。**cacheKey に用いる値は「サーバが解決した後の variant」と「縮退適用後の audioMode」**とする（クライアント指定値や入力値を使うとキーが分裂する。GLM R8 Minor / 予備R）。
- **モード相関検証**（Agy R4-2）: `audioMode` が `added`/`bothMix`/`bothTracks` のとき `addedSourceId` は必須（未指定・解決不能は400）。`original`/`mute` のときは無視する（指定されても使わない）。
- **入力検証**（Qwen R3-8）: `sourceId`/`addedSourceId` は DB 解決と許可ルート制限、`audioMode` は列挙値、各 ms 値は範囲クランプ、型不正は 400。パスは既存の `security.check_path` を通す。

### 3.5 iOS の自動再生制限

- 完了時は**自動再生しない**（`play()` を呼ばない）。位置復元のみ。
- 「反映しました。タップで再生」を表示し、ユーザータップで再生。
- `play()` は全て `.catch()` で捕捉し、失敗時はタップ導線へフォールバック。

### 3.6 クライアントUI

- 「音声タイミング調整」ON/OFF → **「プレビューに反映」ボタン**へ置換。
- 状態: 未反映（設定変更でバッジ）→ 生成中（進捗・キャンセル）→ 反映済み。
- 反映中も**トリム・シーク・コマ送りは全て操作可能**（時間軸同一）。「元に戻る」で元動画へ。
- 診断行に「音声プロキシ表示中（映像加工は書き出し時のみ）」。
- **bothTracks の明示**（Qwen R5-minor）: 反映時に「このモードのプレビューはミックス音声です（書き出しは2トラック）」とUIに表示する。
- **ジョブ token**（Qwen m-4）: build リクエストごとに token を発行し、UI は**最新 token の結果のみ**反映する。生成中の設定変更・別ファイル読込・切断時は token 不一致で破棄。
- **位置復元**（Qwen m-10）: `loadedmetadata` 後に `currentTime` を復元し、`seeked` で確定。失敗時は元動画へロールバック。
- 失敗時: トースト＋元の動画のまま。

## 4. 削除するもの

- `syncAudition` 系（settle / syncAudition / follow / handle / align / ensureAudioGraph / applyAuditionMute / auditionTick / auditionDiag / startAudition / stopAudition / splitLR / auditionWantPlay / auditionSeekLog / auditionDelta）
- `auditionToggle` と関連CSS・静的ガード・動作テスト（C/D/E）
- 書き出しペイロードの `audioTiming`: **`timingInactive` の間は `false`（＝適用しない）で送り**、解除後は常に `true` で送る（GLM R3 M-1: サーバは inactive を知らないため、ペイロード自体で表現する）。解除トリガは「シフト値の変更」「音声モード／追加音声の変更」「プレビューに反映の押下」のいずれか。
- **保存設定の移行**: 旧 `audioTiming:false` は **shift 値を破棄せず**保持し、内部フラグ `timingInactive:true` として「ユーザーが明示的に有効化するまで書き出しに適用しない」状態を維持する（旧データの書き出し結果を変えない・値も失わない）。**解除トリガーは通常データ・移行データ共通で「①シフト値の変更 ②音声モード／追加音声の変更 ③プレビューに反映の押下」の3つ**（GLM R4 M-2: 節内矛盾の解消）。ただし ③ で解除する場合は、**inactive 状態であることを明示した確認**を1回出し、同意した場合のみ解除する（Qwen R6-4: プレビューを見ただけで書き出し挙動が黙って変わるのを防ぐ）。移行テストには「音声モード変更で解除される」ケースも含める。

## 5. 受入基準

1. iPhone Safari で音声が断続しない（単一 `<video>`・単一 MP4）。
2. **音声位置の一致は2系統で判定する**（Qwen R6-3）: (a) プレビュー vs **同一AAC条件の timing-reference 書き出し** の A/V オフセット差 ±5ms（priming/edit list 込みの最終位置）。(b) プレビュー vs **通常書き出し（パケットコピー）**: edit list/priming 分を除いた**内容オフセット**を比較して ±5ms。トリムありは §3.0 の関係式に基づき同一ソース区間で比較する。
3. 反映ボタンの状態遷移が正しく、キャッシュヒット時は即時。
4. 生成失敗時はトースト＋元の動画に戻り、再生位置が保たれる。
5. **既存の書き出し結果が変化しない**（音声位置・コンテナ構造・映像パケット。相互相関／ffprobe／framemd5）。
6. 既存テストスイート全合格（削除したプレビュー同期系を除く）。
7. 機械的に検査可能な静的ガード: `new Audio(` が**ファイル内に存在しない**／`createMediaElementSource` が存在しない／`auditionToggle` が存在しない／`syncAudition` が存在しない（grep で判定）。
8. 反映完了時に `play()` を呼ばない（完了ハンドラ内で `play(` が出現しないことを静的ガード＋VM挙動テスト）。
9. プロキシの尺が映像尺 D と一致（±33ms）。
10. シフトが尺以上のとき全区間無音＋警告。
11. `<key>` が40桁hex以外なら400、認証なしは既存規則で拒否。
12. 映像ストリームが入力バリアントと**同一**（**フレーム内容の checksum のみ**で比較し、PTS列の差は比較対象外。framemd5 の PTS 込み出力をそのまま比較しない）。
13. **プリミング補償後のA/Vオフセット差が ±5ms**（shift=0／shift±500ms／非AAC音声／音源先頭・末尾クランプ／尺パディングの各ケース、timing-reference 出力との比較）。
14. start_time≠0 / edit list 付き素材で、ソース時刻とプレビュー時刻の対応が1フレーム以内。
14. **start_time≠0 / edit list 付き素材で、ソース時刻とプレビュー時刻の対応が1フレーム以内**
19. **itsoffset不成立時のフォールバック経路でも音声位置±5ms・A/V同期が成立**。映像再エンコード時は framemd5 一致を要求しない（ロッシー再エンコードのため、フレーム数と対応フレームの視覚一致で確認）。
20. **10分超の長尺プレビューを再生中にLRUが削除しない**（保護登録・TTL更新・明示解除）。
18. **proxy ジョブ失敗・ポーリング上限到達で無限待ちしない**（UIエラー表示・再送しない）。
17. **copy可能だがブラウザ再生不可のコーデック（HEVC/WebM等）で proxy にフォールバックし、黒画面・無音にならない**。
16. **負シフト時も出力音声の start_time が 0**（atrim後の asetpts を ffprobe で検証）。
15. **`-itsoffset`＋`-c:v copy` の妥当性**（GLM要約R Major-2）: 出力の `start_time` が 0 であること、映像のフレーム数・内容（framemd5）が入力と一致し、余分なフレームや edit list 再生成で1フレームずれないことを確認する。

## 6. 検証方法

- **相互相関**: IN=0/OUT=全尺で preview vs 通常書き出し（同一音声設定）±5ms。トリムありは IN オフセット補正後に比較。
- **モード別**: original / added / bothMix を各モードで比較。bothTracks は preview(mix) と bothMix 書き出しを比較。
- **filter 一致**: モード別に「書き出しが生成する filter 文字列」と「preview が生成する filter 文字列」を単体テストで比較（共通関数化の担保）。
- **映像同一性**: framemd5 で入力バリアントと preview の映像ストリームを比較。
- **尺・仕様**: ffprobe で duration / codec / sample rate / channels。
- **自動再生禁止**: VM ハーネスで完了処理を駆動し `play()` 未呼び出し・タップ導線を確認。
- **後始末**: `.part` が残らない／キャンセル後に残らない／LRU が preview を削除する／使用中キーは削除されない。
- **キャッシュ**: 同一設定2回目でジョブ未発行。設定変更でキー変化。proxy 再生成でキー変化。
- **回帰**: 既存E2E・単体テスト全合格。
- **素材**: 19s/34MB HEVC、長尺10分、非AAC音声、多音声、音声なし、HDR、非ASCII/長パスの各ケース。

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| 長尺で生成が重い／容量 | 既存プロキシ同様に上限なし。空き容量確認・進捗・キャンセル |
| bothTracks はプレビュー=mix | UIに明記。一致保証の範囲を音声タイミングに限定 |
| 反映中のトリム操作 | 時間軸同一のため全て許可（§3.0で正当性を証明） |
| Windows のファイルロック | 削除失敗を捕捉してスキップ |
| iOS 自動再生 | 完了時は自動再生しない＋タップ＋catch |
| HDR 素材 | variant=proxy なら SDR 済み。original が再生可能なら copy（トーンマップ不要） |
| 部分ファイル／破損キャッシュ | `.part`＋アトミックrename、失敗時削除 |
| 旧設定 `audioTiming:false` | 値を保持し `timingInactive` で書き出し不変を維持＋移行テスト |
| preview ファイルの無限蓄積 | LRU 対象に追加・使用中キー保護・ソース削除時に削除 |
| range 配信中に LRU が削除 | 配信中ファイルを保護集合に登録（参照カウント）。Windows の削除失敗は捕捉してスキップ |
| キャッシュの内容変更検知漏れ | contentSig（size+mtime+先頭/末尾64KBのsha1）をキーに含める |
| 品質の取り違え（尺不一致） | 生成後に ffprobe で video/audio duration を比較し、不一致は失敗扱い（再生成） |

## 7.1 実装時の留意事項（レビュー Minor）

- **ffprobe の start_time が N/A／欠損で解析不能**な場合のみ `0.0` にフォールバックする（Agy R6-1）。**負の start_time はクランプしない**（§3.3.1 と同一規則。Agy R12 Major-2）。build 応答の `sourceTimelineOffsetUs` は**variant映像ストリームのstart_time**、`outputStartOffsetUs` は**生成後の実測値**であり、両者の役割を混同しない。
- **元素材に音声が無く追加音声だけがある**場合、`audioMode=bothMix`/`bothTracks` でも内部で `added` 単一モードへ縮退する（`amix=inputs=2` の初期化エラー防止。Agy R6-2）。
- **cacheKey の canonical 化**: 未指定項目は一律 `null` として残し、入力辞書のデフォルトを確定してから `json.dumps(sort_keys=True)` に渡す（Agy R6-3）。
- 追加音声が映像より短い場合の無音扱い・警告は書き出し側の既存規則を再利用する。
- **build 応答の時間軸オフセットは2フィールド契約**（`sourceTimelineOffsetUs`=UI写像用、`outputStartOffsetUs`=診断用）。単一フィールドに戻さない。
- **クライアントの時刻変換は `sourceTime − sourceTimelineOffsetUs` に統一**し、単体テストで強制する（Agy R8-1: 旧変数名の残存を除去）。
- **contentSig は将来のストリーミングソース向けに**「先頭のみ／DB保存ハッシュ優先」へ差し替え可能なインターフェースにしておく（現行はローカルのみ。R7-2）。
- **timing-reference は内部専用ジョブ種別**（`export-timing-ref`）とし、キューの最低優先度または検証CLI経由で実行して通常の書き出しを妨げない（R7-3）。
- **受入2(b)の測定手順**: 映像フレームを framemd5 で対応付け、同一映像区間のPCMを相互相関して**内容オフセット**を求める（コンテナの edit list/priming は除外）。許容 ±5ms（R7-4）。
- **保護規則の追加**（Qwen R9-1 / R11）: 「読み込み中キー」をセッション保護集合に追加してよい（§3.2 の正判定を置き換えず、安全側の追加として扱う）。
- **追加音声側の正規化**（Qwen R9-2）: `addedAudioStart` を追加音声ストリームから取得し、総遅延を `addedShiftMs + addedRel` に正規化する。受入に addedSource の start_time≠0 ケースを追加。
- **負TS・非単調DTS対策**（Qwen R9-3 / GLM R10 Minor）: **入力側**に `-fflags +genpts`、**入力側**に `-fflags +genpts` を付ける。**`-avoid_negative_ts make_zero` は使わない**（実測で映像copyのPTSが約66msずれ、start_time≠0 とA/Vずれを生むため）。出力 start_time=0 を ffprobe で検証する。
- **数値の書式化**（Agy R10-1）: `atrim=start=` / `adelay=` の数値は固定小数点（例: `f"{-tot_sec:.6f}"`）で生成し、指数表記や過剰桁で ffmpeg の構文解析が失敗しないようにする。
- **追加音声が複数ストリームを持つ場合**は選択ストリームの start_time を rel に使う（音声ごとに rel を分けない）。
- **追加音声の総遅延**（Agy R10-2）: `tot_added_sec = ((addedShiftMs + addedStartMs) / 1000.0) + addedRel_sec` として addedStartMs も合算する（単体テストで確認）。
- **音声なし素材の iOS 実機確認**: 音声ストリームを含まない MP4 で、シーク・位置復元が正常に完了することを検証項目に含める（Agy R7-2）。

## 8. 段取り

1. 計画レビュー（三者）→ 完全Go **済み**
1.5. **共通音声関数の抽出前検証**（GLM R3 M-2）: 現行書き出しの全モードの filter 末尾が共通後段（apad/atrim による尺固定）と既に等価かを、既存テストと framemd5／ffprobe で先に確認する。等価でない場合は共通後段を **preview 専用フラグ**として共通関数に渡し、filter 一致テストの比較対象を「後段を除く本体グラフ」に限定する（書き出し出力は不変に保つ）
2. 実装（共通音声関数の抽出 → サーバ → UI → テスト）
3. 成果物レビュー（三者）
4. テスト設計レビュー（GLM）＋ `docs/TEST_DESIGN.md` 更新
5. 検証・commit/push・`docs/REVIEW.md` 追記
