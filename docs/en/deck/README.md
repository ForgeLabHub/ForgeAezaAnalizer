# Presentation generator

English version of [../../deck/README.md](../../deck/README.md).

The scripts in this directory build defence presentations from the application data.
The numbers come from the domain modules and `dataset/data.json`.

## Build

From the project root:

```bash
pip install -r requirements-dev.txt
python3 docs/deck/build_deck.py umirhack
python3 docs/deck/build_deck.py hackathon
```

The `both` variant builds both presentations. Interface screenshots live in `shots/`, brand
assets in `brand/`.

To check a finished presentation:

```bash
python3 docs/deck/validate.py aeza_umirhack_defense.pptx
python3 docs/deck/qa_visual.py aeza_umirhack_defense.pptx
```
