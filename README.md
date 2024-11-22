# Скрипт для удаления неудачных деплойментов
используется в k8s QA кластере

## Что делает скрипт
- ищет все неймспейсы по лейблу "hnc.x-k8s.io/included-namespace=true"
- в каждом найденном неймспейсе ищет поды по таким критериям:
    - owner: ReplicaSet
    - state: ! running
    - creation_timestamp > 3-х дней от текущей даты
- по названию отфильтрованных подов ищет деплойменты у которых кол-во желаемых реплик равно кол-ву недоступных
- удаляет эти деплойменты

## Параметры запуска
- --dry - искать все неудачные деплойменты, выводит сообщение об удалении но при этом не удаляет их. В логах отражается как "[DRY RUN]"
- --local - необходим для запуска скрипта локально, со своего устройства, при указании этого параметра для подключения к k8s считывается конфигурационный файл ~/.kube/config. По умолчанию скрипт пытается считать токен сервис аккаунта и работает только внутри k8s кластера.


