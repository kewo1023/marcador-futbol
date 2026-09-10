# marcador-futbol

*[Versión en español](README.md)*

A football forecasting system that grades itself: it records predictions before
matches are played, ingests the results, measures itself against the market, and
**decides on its own** whether to swap models.

**The thesis:** you build the system that judges the model before you build the
model. Anything that "corrects itself" needs to know in which direction to
correct, and only a measurement system that already exists can tell it that.

### Where to start reading

| If you want to… | Go to |
|---|---|
| See what worked and what didn't, unvarnished | **[LEARNINGS.md](LEARNINGS.md)** |
| See the measured result | [The scoreboard](#the-scoreboard), below |
| Understand why the model can't degrade itself | [The promotion gate](#the-promotion-gate) |
| Read the engine | [`src/marcador/dixon_coles.py`](src/marcador/dixon_coles.py) |
| See how data leakage is prevented | [`src/marcador/db.py`](src/marcador/db.py) — triggers, not documentation |
| Audit the predictions without trusting anyone | [`ledger/`](ledger/) and `git log` |

Code comments and the full documentation set are in Spanish. This file and
[LEARNINGS.md](LEARNINGS.md) cover everything a reader needs.

### The three-line summary

The final model scores **0.9786** log loss. Elo scores 0.9845 and the market
0.9556. Against Elo the model is ahead, but the confidence interval crosses zero
(p = 0.147): **it's a draw with an edge, not a win**, and it's reported that way.
Against the market it loses, and that one is conclusive.

Of four markets built on the same engine, **one** beats its base rate
demonstrably.

## The scoreboard

Walk-forward backtest on the Premier League. Eleven seasons split into 3 for
warm-up, 3 for validation (where hyperparameters are chosen) and **5 for test,
which are the only ones reported**. Choosing `xi` while looking at the same
seasons you later report on would be leakage — it doesn't enter through the
features, it enters through the decision of which hyperparameter to use.

| Model | Log loss ↓ | Brier ↓ | Accuracy | % of headroom covered |
|---|---|---|---|---|
| Base rate | 1.0679 | 0.6461 | 44.2% | — (the floor) |
| Plain Poisson | 1.0086 | 0.6021 | 50.7% | 52.8% |
| Elo | 0.9845 | 0.5871 | 54.3% | 74.3% |
| Poisson + time decay | 0.9829 | 0.5838 | 53.3% | 75.7% |
| Dixon-Coles (+ rho) | 0.9826 | 0.5837 | 53.3% | 75.9% |
| **Dixon-Coles + regularisation** | **0.9786** | **0.5823** | 53.2% | **79.5%** |
| Market (closing, vig removed) | 0.9556 | 0.5670 | 55.9% | — (the ceiling) |

Note the final model has *lower* accuracy than Elo and is still better. Accuracy
is shown as context and decides nothing.

### What each piece contributed

Paired comparison on the same matches, 20,000 bootstrap resamples. Negative means
improvement.

| Change | Difference | 95% CI | Conclusive? |
|---|---|---|---|
| Time decay | −0.0257 | [−0.0355, −0.0156] | **yes** |
| `rho` low-score correction | −0.0002 | [−0.0012, +0.0007] | no |
| Regularisation | −0.0040 | [−0.0093, −0.0002] | **yes** |
| Final model − Elo | −0.0059 | [−0.0137, +0.0020] | no |
| Final model − market | +0.0230 | [+0.0151, +0.0309] | **yes** (market wins) |

**Time decay is the whole gain.** A Poisson model that treats a 2015 match the
same as last week's is *worse* than Elo. **`rho` contributes nothing** — half the
model's name is dead weight on modern Premier League data.

## The promotion gate

**The rule, in one line: the champion keeps the title unless it is beaten
conclusively. A tie goes to the champion.**

Every Monday a new configuration is searched for on a tuning block and put up
against the champion on three seasons **neither of them has seen**. Both are
refitted with the same procedure: comparing the champion as-is against a
freshly-trained challenger would always favour the challenger for having newer
parameters.

The decision uses a paired bootstrap, not a comparison of averages. The reason is
documented in this repo's own history: an early version declared the model "beats
Elo by 0.0018" and it was noise. A gate comparing averages would promote every
time chance handed over a tenth of an edge — and since promotion compounds, the
system would degrade on imaginary improvements. Which is exactly what this phase
exists to prevent.

The first real challenge was a **rejection**: the challenger won on the tuning
block and lost on the gate block.

The production model lives in `ledger/champion.json`, **not in the code**. If it
were a Python constant, promoting would require a human to edit a `.py` — the
system wouldn't be correcting itself, it would be asking permission.

## Four markets on one engine

Switching markets means switching which column the two counts come from. The
engine doesn't know whether it's counting goals, corners, cards or shots.

Two caveats that only appear once you measure:

**Poisson isn't enough everywhere.** Residual dispersion over 790 matches, with
team strength already accounted for: goals 0.86, cards 0.86, shots on target
0.99 — fine. Corners 1.34 and total shots 1.46 — not fine. For those two the
predictive distribution becomes negative binomial; the mean is still estimated by
the same engine.

**The raw model lost to the base rate on corners.** Shrinking toward the base
fixes it, and the optimal weight per market measures how much the model can be
trusted there — independently reproducing the signal ranking.

| Market | Beats its base rate? | p |
|---|---|---|
| **Cards 2.5 / 3.5 / 4.5** | **Yes, all three** | 0.038 / 0.000 / 0.029 |
| Corners (4 lines) | Positive, not conclusive | 0.12 – 0.94 |
| Goals over/under (3 lines) | Positive, not conclusive | 0.39 – 0.59 |
| Shots on target (3 lines) | Positive, not conclusive | 0.16 – 0.76 |

The source publishes closing odds for 1X2 and over/under 2.5 goals only. Corners,
cards and shots are measured **against the base rate alone**: you learn whether
the model adds something, not how far it is from what's achievable.

## How it's built, one line per piece

- **Raw data never enters the repo.** `data/` is gitignored; what's published is
  predictions and derived metrics.
- **Predictions are immutable**, and not by discipline: the database aborts any
  `UPDATE` or `DELETE` on them with a trigger.
- **No feature uses information from the future**, also enforced by the database:
  a prediction whose information cutoff post-dates the match is rejected.
- **Every backtest is walk-forward**, grouped by date so two matches on the same
  day can't leak into each other.
- **No comparison between models is made on averages**: they all go through a
  paired bootstrap, because a 0.002 log-loss difference over 1,700 matches sits
  comfortably inside the noise.
- **The production model lives in a versioned file, not in code**, which is what
  lets the gate promote without human intervention.

## Running it

Requires Python 3.11+. Phase 1 runs on the standard library alone.

```bash
python3 scripts/01_ingest.py     # download historical CSVs -> data/marcador.sqlite
python3 scripts/02_baseline.py   # baseline predictions and the scoreboard

python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scripts/03_dixon_coles.py   # fit, backtest, compare
./.venv/bin/python scripts/06_retrain.py --dry-run   # what the gate would decide
./.venv/bin/python scripts/08_markets.py             # the four markets
./.venv/bin/streamlit run dashboard/app.py           # dashboard on localhost:8501
```

## Data source

[football-data.co.uk](https://football-data.co.uk) — free per-season, per-league
CSVs with results, corners, cards, shots, shots on target, referee and closing
odds from several bookmakers.

## Licence

MIT for the code — see [LICENSE](LICENSE). The data belongs to its respective
sources and is not redistributed here.
