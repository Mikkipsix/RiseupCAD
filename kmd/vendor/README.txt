PySocks 1.7.1 (BSD-3-Clause), встроен в комплект.

Нужен pip, чтобы ходить через прокси socks5://. Без него pip падает с
«Missing dependencies for SOCKS support» ещё до обращения к сети, а
скачать сам PySocks через тот же неработающий pip невозможно - замкнутый
круг. Поэтому модуль лежит здесь и подкладывается в PYTHONPATH при
установке библиотек.

Лицензия: LICENSE_PySocks.txt
