# haas-mac-dictation

Apple Silicon Mac 上で日本語音声認識モデル [Haas-ja-v1.0](https://huggingface.co/third-intelligence/Haas-ja-v1.0)（`speech.cpp` Metal 推論）とディクテーションクライアント [OpenWhispr](https://github.com/OpenWhispr/openwhispr)（または VoiceInk）をつなぐ軽量中継スクリプトと launchd 設定です。

> [!WARNING]
> 実験的な構成です。動作を確認したのは作者の環境1台（macOS 26、Apple M2、`speech.cpp` 0.10.0、OpenWhispr 1.11.0）だけで、`setup.sh` を新しい環境で実行して試してはいません。
>
> - 下の図の「認識 0.29〜0.41秒」は、OpenWhispr から3〜8秒の文を話した8回の `speech serve` の処理時間で、話し終えてから文字が入力されるまでの時間ではありません。起動直後などに数秒〜20秒台かかった回もあります。図の元は `images/architecture.html` です。
> - `proxy.py` は既定では認識結果をログに残しません。`HAAS_LOG_TEXT=1` を指定したときだけ、応答の先頭（200バイト）を `~/.local/share/haas-dictation/proxy.log` に記録します。
> - OpenWhispr の通信をすべて確認したわけではありません。外部に送信しないことは保証できません。

![ローカル日本語音声入力の3段構成](images/architecture.png)

## 役割 (`proxy.py`)

- `speech.cpp` が `400 Bad Request` で拒否する未対応フィールド（`prompt`、`temperature`、`model` など）を除去
- `keywords.txt` に記載したカスタム語彙（`表記=読み1,読み2`）を `keywords[]` として自動付与
- OpenWhispr が送信する `/v1/chat/completions`（テキスト補正）リクエストに対し、`<transcript>` 内の本文のみを抽出して `200 OK` で返却
- WebM/Opus 等の非 WAV 音声を `ffmpeg` で 16kHz モノラル PCM WAV に自動変換
- 90秒を超える長尺音声のみ `chunking_strategy=auto`（`silero-vad`）を付与し、通常の長さの発話では句読点の脱落を防止

## セットアップ

```sh
brew install ffmpeg
brew install --cask openwhispr

git clone https://github.com/akitana-airtanker/haas-mac-dictation.git
cd haas-mac-dictation
./setup.sh
```

`setup.sh` は次のことを行います。

- `~/.local/bin/speech` がなければ、[speech.cpp の公式インストールスクリプト](https://github.com/nyosegawa/speech.cpp/blob/v0.10.0/install.sh)で検証した版の 0.10.0 を入れる（`SPEECH_VERSION=0.10.1 ./setup.sh` のように版を変えられる）。既にあれば入れ直さない
- `haas-ja-v1.0` と `silero-vad` のモデルを取得する
- `proxy.py` を `~/.local/share/haas-dictation/` に上書きでコピーする。`keywords.txt` はなければコピーする
- `~/Library/LaunchAgents/` に2つの plist を書き、`local.haas.speech-serve` と `local.haas.proxy` を登録し直す

### OpenWhispr 側の設定

1. Finder または Dock から **OpenWhispr** を起動します（ターミナルの子プロセスとして起動すると macOS TCC によりマイク入力が遮断されます）。
2. **音声認識 → セルフホスト** を選択し、以下を設定します。
   - サーバー URL：`http://127.0.0.1:8081/v1`
   - モデル：`Haas-ja-v1.0`
3. **言語モデル → ディクテーションのクリーンアップ** で「テキスト補正を有効にする」をオフにします。

## カスタム語彙の追加

`~/.local/share/haas-dictation/keywords.txt` に `表記=読み1,読み2` を1行ずつ追記して保存すると、再起動なしで次の発話から反映されます。

## テスト

```sh
python3 -m unittest discover -s tests
```

入力を乱数（シード固定）で生成し、未対応フィールドの除去、語彙の付与、90秒を超える音声だけへの分割指定、`<transcript>` の抽出を確かめます。

## 停止・アンインストール

```sh
./uninstall.sh
```

## ライセンス

MIT
