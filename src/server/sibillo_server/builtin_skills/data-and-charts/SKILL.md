---
name: data-and-charts
description: Use to analyse tables of data (CSV, Excel, JSON, SQLite), compute totals and statistics, make charts, and handle archives and unknown files.
---

# Data and charts

python3 has pandas, numpy and matplotlib; the shell has jq, sqlite3, file, zip and unzip, and
Node.js (`node`, with `npm`). Install nothing that is already here.

## Tables with pandas

```python
import pandas as pd

frame = pd.read_csv("bank.csv", sep=None, engine="python")  # guesses ; or , as separator
frame["date"] = pd.to_datetime(frame["date"], dayfirst=True)
monthly = frame.groupby(frame["date"].dt.to_period("M"))["amount"].sum()
print(monthly.to_string())
monthly.to_csv("/workspace/budget/monthly.csv")
```

Excel: `pd.read_excel(path, sheet_name=None)`; JSON: `pd.read_json(path)` or
`pd.json_normalize(data)`. Print what you computed, not whole tables: the user reads your answer.
Use numpy for arrays and statistics that pandas does not cover.

## Charts with matplotlib

```python
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
monthly.plot(kind="bar", ax=ax)
ax.set_title("Spending by month")
ax.set_ylabel("EUR")
fig.savefig("/workspace/budget/monthly.png", dpi=150)
```

Offer the image to the user with `offer_download`. Label axes and units, start bars at zero, and
keep to one message per chart.

## JSON, SQLite and other tools

- jq: `jq '.items[] | {name, price}' data.json`, `jq -r '.[] | [.a, .b] | @csv' data.json`.
- sqlite3: `sqlite3 data.db '.tables'`, `sqlite3 -header -csv data.db 'SELECT ...'`. For large
  CSV files, `.import --csv big.csv t` and query them with SQL.
- file: `file unknown.bin` says what a file is when its name does not.
- zip and unzip: `unzip -l archive.zip` lists, `unzip archive.zip -d /scratch/x` extracts,
  `zip -r out.zip folder` makes one.
- node runs JavaScript; `npm install` works for this answer only, in a folder of your own.
