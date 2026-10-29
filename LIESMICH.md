# LIESMICH: bitte vor der nächsten Version lesen

Hey, ich habe auf 2.15.0 ein paar Sachen gefixt: Coaching-Texte, Utility-Bug, Deathmatch-Sperre,
eine Sicherheitslücke im Strat-Board und einiges mehr. Was genau und warum steht in **[CHANGES.md](CHANGES.md)**.

**Das Problem bisher:** Meine Fixes sind schon zweimal verloren gegangen, weil die neue Version einfach
über den Ordner entpackt wurde. Darum ist das Projekt jetzt ein **Git-Repo** (der Ordner `.git`).

## Was im Repo ist

| Stand | Was |
|---|---|
| Tag `v2.15.0-original` | deine 2.15.0, unverändert |
| Branch `main` | 2.15.0 + meine Fixes |

Was ich geändert habe: `git diff v2.15.0-original main` (oder `git log -p`).

## Wenn du seit 2.15.0 weitergearbeitet hast

Deine Änderungen **nicht** über den Ordner kopieren, sondern so zusammenführen:

```bash
cd valcoach-v2
git switch -c mein-stand v2.15.0-original     # neuer Branch auf deiner 2.15.0
# jetzt deine neuen Dateien hineinkopieren (ohne .git, data/, .venv/)
git add -A
git commit -m "Meine Änderungen seit 2.15.0"
git switch main
git merge mein-stand
```

- **Kein Konflikt:** alles gut, deine und meine Änderungen sind beide drin.
- **Konflikt:** Git zeigt die Stellen mit `<<<<<<<` / `>>>>>>>` an. Dort haben wir beide dieselben Zeilen
  geändert. Bitte beide Versionen zusammenführen, nicht einfach deine nehmen. Dann `git add <datei>` und
  `git commit`.
- Danach `pytest -q`: Alle Tests müssen grün sein. Meine Tests stehen am Ende von `tests/test_pipeline.py`
  und `tests/test_web.py` (Abschnitt *review fixes*).

## Ab jetzt

- Immer im Repo arbeiten und committen, statt Zips über den Ordner zu entpacken.
- Neue Version weitergeben: den ganzen Ordner **mit `.git`** zippen (ohne `data/` und `.venv/`).
- Noch einfacher: ein privates Repo auf GitHub oder GitLab, dann `git pull` / `git push`.

**Ohne Git** geht es auch mit der Datei `valcoach-fixes.patch` (`patch -p1 < valcoach-fixes.patch`
auf einer frischen 2.15.0). Bei Konflikten ist Git aber viel einfacher.

Achtung beim Strat-Board: Neue Felder für Board-Elemente müssen in `ITEM_NUMBERS` / `ITEM_STRINGS`
in `valcoach/web/strats.py` eingetragen werden, sonst verwirft der Server sie beim Speichern (Schutz gegen eingeschleusten Code).
