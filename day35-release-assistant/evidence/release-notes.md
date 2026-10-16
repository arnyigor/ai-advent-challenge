# DnsHostsGenerator — материалы обновления

Статус: Проверки пройдены · требуется просмотр.

Диапазон: 7ca367d33b2d8b4b0e751e900236e7937e4a8b11 → 13da58f60d53fe2f3aa05246cdb5d1f9bdbbd5b1.
Модель: gemini:gemini-3.8-flash.

## Обновление компонентов и форматов

### Поддержка альтернативных форматов экспорта [S14, S21]
- Реализован экспорт сгенерированного результата в форматах **dnsmasq (.conf)**, **AdGuard** и списка для **NextDNS**, помимо стандартного hosts.
- В форматы правил выгружаются только успешно разрешённые домены без диагностических пометок.

### Улучшение импорта списков и поддержка архивов [S7, S17, S20, S21, S28]
- В карточках групп добавлена возможность импорта списков доменов прямо из **ZIP-архивов**.
- Парсер ввода теперь автоматически нормализует форматы hosts, dnsmasq и AdGuard/zapret, предотвращая попадание синтаксического мусора в базу данных [S17, S22].

### Изменения в DNS-пресетах и защите от некорректных ответов [S11, S16, S23]
- Добавлены новые DoT-пресеты: `dns.bezmezhau.com` и `dns.zapret.moe` [S11].
- Пресет `xbox-dns.ru` отключён по умолчанию из-за возврата `0.0.0.0` на запросы ИИ-сервисов [S11, S23].
- Добавлена фильтрация null-route адресов (`#blocked`) и прерывание генерации, если выбранный DNS обнуляет все запрашиваемые домены [S15, S16].

### Системный hosts на Desktop [S21, S29]
- Для настольной версии добавлена функция прямого обновления файла hosts операционной системы с автоматическим созданием резервной копии.

### База данных доменов [S10, S12, S13]
- Актуализирован начальный состав доменов и групп (добавлена группа Badoo, новые адреса для Gemini, Claude, Grok, Copilot).

*Версия сборки Android повышена до 1.4.1 (141) [S4], версия пакета Desktop — до 1.4.1 [S6].*

## Фактические проверки

- shared-jvm-tests: passed; SHA 13da58f60d53fe2f3aa05246cdb5d1f9bdbbd5b1
- android-debug: passed; SHA 13da58f60d53fe2f3aa05246cdb5d1f9bdbbd5b1
- desktop-package: passed; SHA 13da58f60d53fe2f3aa05246cdb5d1f9bdbbd5b1

Debug APK не является production-публикацией в магазин.

## Источники

- [S1] .github/workflows/build-apps.yml (context)
- [S2] README.md (context)
- [S3] IMPROVEMENTS_4PDA.md (diff)
- [S4] androidApp/build.gradle.kts (diff)
- [S5] androidApp/src/main/kotlin/com/arny/dnshostsgenerator/MainActivity.kt (diff)
- [S6] desktopApp/build.gradle.kts (diff)
- [S7] shared/src/androidMain/kotlin/com/arny/dnshostsgenerator/platform/FilePicker.android.kt (diff)
- [S8] shared/src/androidMain/kotlin/com/arny/dnshostsgenerator/platform/SystemHostsUpdater.android.kt (diff)
- [S9] shared/src/androidMain/kotlin/com/arny/dnshostsgenerator/platform/ZipArchive.android.kt (diff)
- [S10] shared/src/commonMain/composeResources/files/seed_data.sql (diff)
- [S11] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/data/BuiltInDnsPresets.kt (diff)
- [S12] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/data/DefaultDomainList.kt (diff)
- [S13] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/data/DomainSeed.kt (diff)
- [S14] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/domain/HostsExporters.kt (diff)
- [S15] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/domain/Models.kt (diff)
- [S16] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/generator/HostsGenerator.kt (diff)
- [S17] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/nextdns/HostsParser.kt (diff)
- [S18] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/platform/FilePicker.kt (diff)
- [S19] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/platform/SystemHostsUpdater.kt (diff)
- [S20] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/platform/ZipArchive.kt (diff)
- [S21] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/presentation/HostsGeneratorScreen.kt (diff)
- [S22] shared/src/commonMain/kotlin/com/arny/dnshostsgenerator/presentation/HostsGeneratorViewModel.kt (diff)
- [S23] shared/src/commonTest/kotlin/com/arny/dnshostsgenerator/data/DisabledPresetsTest.kt (diff)
- [S24] shared/src/commonTest/kotlin/com/arny/dnshostsgenerator/domain/HostsExportersTest.kt (diff)
- [S25] shared/src/commonTest/kotlin/com/arny/dnshostsgenerator/generator/HostsGeneratorTest.kt (diff)
- [S26] shared/src/commonTest/kotlin/com/arny/dnshostsgenerator/nextdns/HostsParserTest.kt (diff)
- [S27] shared/src/commonTest/kotlin/com/arny/dnshostsgenerator/platform/ZipArchiveTest.kt (diff)
- [S28] shared/src/jvmMain/kotlin/com/arny/dnshostsgenerator/platform/FilePicker.jvm.kt (diff)
- [S29] shared/src/jvmMain/kotlin/com/arny/dnshostsgenerator/platform/SystemHostsUpdater.jvm.kt (diff)
- [S30] shared/src/jvmMain/kotlin/com/arny/dnshostsgenerator/platform/ZipArchive.jvm.kt (diff)
- [S31] shared/src/jvmTest/kotlin/com/arny/dnshostsgenerator/data/SeedDataSqlTest.kt (diff)
- [S32] shared/src/jvmTest/kotlin/com/arny/dnshostsgenerator/resolver/LiveDnsVerificationTest.kt (diff)
