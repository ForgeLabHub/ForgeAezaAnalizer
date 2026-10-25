# Генератор презентации

Скрипты в этом каталоге собирают презентации для защит из данных приложения. Расчёты берутся из доменных модулей и dataset/data.json.

## Сборка

Из корня проекта:

~~~bash
pip install -r requirements-dev.txt
python3 docs/deck/build_deck.py umirhack
python3 docs/deck/build_deck.py hackathon
~~~

Вариант both собирает обе презентации. Скриншоты интерфейса находятся в shots/, ресурсы бренда — в brand/.

Чтобы проверить готовую презентацию:

~~~bash
python3 docs/deck/validate.py aeza_umirhack_defense.pptx
python3 docs/deck/qa_visual.py aeza_umirhack_defense.pptx
~~~
