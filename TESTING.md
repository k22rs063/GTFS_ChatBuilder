# 動作確認チェックリスト

下から上へ積み上げる構成:
**プロセッサ(決定論部分) → Python @tool → エージェント(LLM) → UI**

各レイヤで切り分けると、不具合が「LLM 由来か / 変換ロジック由来か / 配線か」を
1ステップで特定できる。

---

## 0. セットアップ前提

- [ ] uv 0.11+ (`uv --version`)
- [ ] `.venv/` が存在する (`uv sync` 済み)
- [ ] `.env` がプロジェクト直下にあり `LOCAL_BASE_URL` / `LOCAL_MODEL` / `LOCAL_API_KEY` が設定されている
- [ ] LM Studio (またはその他 OpenAI 互換 API) が起動していて `LOCAL_BASE_URL` で疎通可能
- [ ] `workspace/stops.txt` と `workspace/sample_timetable.csv` がある

---

## 1. プロセッサレイヤ (LLM 抜きの決定論動作)

Python REPL で純粋関数を直接呼び、変換ロジック単独の挙動を確認する。

```powershell
uv run python
```

### 1-1. stop_times プロセッサ

```python
from gtfs_chatbuilder.processors.stop_times import process_stop_times_data
from pathlib import Path
stops = Path("workspace/stops.txt").read_text(encoding="utf-8")
csv   = Path("workspace/sample_timetable.csv").read_text(encoding="utf-8-sig")
print(process_stop_times_data(stops, csv))
```

- [ ] 1 行目が `trip_id,arrival_time,departure_time,stop_id,stop_sequence,...`
- [ ] 各便の始発に `drop_off_type=1` / 終着に `pickup_type=1` が付く
- [ ] `stop_name` で始まらないヘッダを入れると `ValueError` が出る

### 1-2. shapes プロセッサ

```python
from gtfs_chatbuilder.processors.shapes import process_shapes_data
coords = "130.123,33.456,0\n130.234,33.567,0\n130.345,33.678,0"
print(process_shapes_data("shape_test", coords))
```

- [ ] 1 行目が `shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence`
- [ ] 経度が 9 桁ゼロ埋め (`130.12300`)、緯度が 8 桁ゼロ埋め (`33.45600`)
- [ ] `shape_pt_sequence` が `1,2,3` の順

### 1-3. kml プロセッサ

```python
from gtfs_chatbuilder.processors.kml import process_kml_data
from pathlib import Path
kml = Path("workspace/sample_route.kml").read_text(encoding="utf-8")
print(process_kml_data(kml))
```

- [ ] `[{"name": ..., "coordinates": ...}, ...]` の list が返る
- [ ] LineString / Polygon / gx:Track の 3 形式に対応
- [ ] 不正な KML で `ValueError` が出る (例外で UI が壊れない)

---

## 2. Python @tool レイヤ (LLM 抜き)

Python REPL で `tool.invoke({...})` を直接呼ぶ。ファイル入出力と
エラーメッセージ整形を単独で確認する。

```python
from gtfs_chatbuilder.tools.stop_times import generate_stop_times_from_csv
from gtfs_chatbuilder.tools.shapes    import generate_shapes_from_coordinates
from gtfs_chatbuilder.tools.kml       import convert_kml_to_coordinates
```

### 2-1. stop_times

- [ ] `generate_stop_times_from_csv.invoke({"input_csv_filename": "sample_timetable.csv"})` → `workspace/stop_times.txt` が生成され、戻り値に行数が含まれる
- [ ] `.xlsx` を渡すと各シートを処理して連結される (シート数も戻り値に表示)
- [ ] 存在しないファイル名を渡すと `エラー: ...見つかりません:` で始まる文字列が返る (例外を投げない)

### 2-2. shapes

- [ ] `generate_shapes_from_coordinates.invoke({"shape_id": "shape_1", "coordinates_filename": "coords_test.txt"})` で `workspace/shapes.txt` 生成
- [ ] 戻り値に shape_id と行数が含まれる

### 2-3. kml

- [ ] `convert_kml_to_coordinates.invoke({"kml_filename": "sample_route.kml"})` で `workspace/<basename>__<name>.txt` が生成される
- [ ] 同名 placemark が複数あるとき `__name_2.txt` のように衝突回避される
- [ ] 戻り値に「shape ツールに渡せばよい」案内が含まれる

---

## 3. エージェントレイヤ (LLM 経由)

`python run.py` で Streamlit を起動してブラウザから操作。

### 3-1. 単純なツール呼び出し

- [ ] `sample_timetable.csv から stop_times を作って` → 確認画面が出る → 「実行する」で `workspace/stop_times.txt` 生成
- [ ] 続けて KML を置いて `sample_route.kml から座標を抽出して` → 確認画面 → 経路ファイル生成

### 3-2. ハルシネーション抑制 (本プロトタイプの主目的)

LLM が値や名前を勝手に作らないことの確認。

- [ ] 「stop_times を作って」だけ送る → **CSV ファイル名を質問してくる** (ファイル名を勝手に決めない)
- [ ] 「shapes.txt を作って」だけ送る → **shape_id と座標ファイル名の両方を質問してくる**
- [ ] 「停留所の座標を入れて stops.txt を作って」と頼む → **そんなツールはないので作れない、という応答になる** (緯度経度を捏造しない)

### 3-3. 利用者確認層

- [ ] 書き込み系ツール (`generate_stop_times_from_csv` / `generate_shapes_from_coordinates` / `convert_kml_to_coordinates`) を呼ぶと、実行前に **確認画面** が出る
- [ ] 確認画面に「ツール名 (日本語)」「引数のテーブル表示」が出る
- [ ] 「✓ 実行する」で続行、「✗ やり直す」で拒否されて続行されない

### 3-4. ツール選択 (docstring だけで識別できるか)

- [ ] 「時刻表から GTFS を作って」 → `generate_stop_times_from_csv`
- [ ] 「KML の座標を取り出して」 → `convert_kml_to_coordinates`
- [ ] 「進捗を見せて」 → `get_project_status` (確認画面を経ず即時応答)

### 3-5. 複数ステップ (KML → shapes)

同じ thread で連続実行できるか:

- [ ] 「`route.kml` から座標を取り出して」 → 確認 → kml ツール実行、抽出ファイル名が応答に出る
- [ ] 直後に「`shape_1` でその座標から shapes.txt を作って」 → 確認 → **前ステップで生成されたファイル名を引き継ぐ**

### 3-6. エラーハンドリング

- [ ] 存在しないファイル名を含む依頼を投げる → エージェントがエラー文字列を受け取り、ユーザーに「そのファイルは見つからない」と返す
- [ ] LLM への接続が切れた状態で起動 → UI 上でエラー表示 (Streamlit がクラッシュしない)

### 3-7. UI 基本動作

- [ ] サイドバーの「📤 ファイルをアップロード」で xlsx / csv / kml / txt を保存できる
- [ ] サイドバーの「📋 時刻表を貼り付け」で Excel 直接コピペ (タブ区切り) が CSV として保存される
- [ ] 「作成中のファイル」一覧の「✕」で個別削除できる
- [ ] 「📥 GTFS データを ZIP でダウンロード」で `.txt` のみ ZIP 化される
- [ ] 「会話をリセット」で履歴がクリアされる

---

## 4. データ整合性 (任意・実データとの突き合わせ)

- [ ] 生成した `stop_times.txt` を ChikujoBusGTFS の実 `stop_times.txt` と
      列構造で並べて目視確認
- [ ] 生成した `shapes.txt` の lat/lon を地図にプロットして経路として成立するか確認

---

## 既知の注意点

- Streamlit の `@st.cache_resource` でエージェントをキャッシュしているため、
  `agents.py` を編集してもキャッシュが効いて反映されない場合がある。
  その場合は Streamlit を再起動する。
- `InMemorySaver` なので、Streamlit を再起動すると会話履歴は消える
  (ワークスペースのファイルは残る)。
- `workspace/coords_test.txt` などテストごみは `.gitignore` 推奨。
