# Контракт v1

Зафиксирован до реализации. CLI и HTTP используют один `runRelease(options)`.
Профиль — DnsHostsGenerator, распространение: debug APK и desktop distributable.

Вход: repo (локальный Git), base/head (явные refs), provider/model,
runChecks (явный запуск сборочных проверок), collectOnly. Ref разрешается в SHA.
Base обязан быть предком head. Для всех запросов один зарегистрированный repo;
HTTP не принимает произвольный путь или shell-команду.

Evidence: schema_version, run_id, repository, base_sha, head_sha,
working_tree_dirty, commits, changed_files, sources [{id,path,kind,text}],
omitted_files, truncated_sources, coverage_complete, checks.

Analysis: changes [{category,title,user_impact,evidence_ids}],
risks [{severity,scenario,evidence_ids}],
manual_checks [{action,expected_result,evidence_ids}], uncertainties [string],
release_notes (string). Каждое evidence_ids — непустой список известных ID.
Все текстовые ссылки [S1] также проверяются. JSON не исполняется как код/HTML.

Check: id, argv, tested_sha, required, status, exit_code, duration_ms, log_path.
Статусы: passed / failed / not_run / unavailable / timeout.
Проверки выполняются в отдельном clone checkout head_sha без секретов проекта.
Логи не передаются модели; только статусы, команды из профиля и краткая сводка.

Run: id, state (running/done/error), stage, events, evidence, analysis,
model, usage, error, result_status, artifacts.
blocked: обязательная проверка failed/timeout. incomplete: отсутствует AI,
неполное покрытие, нет изменений, проверка не выполнена/недоступна/для иного SHA.
checks_passed_review_needed: AI валиден, покрытие полное, обязательные проверки
пройдены на head_sha. Это не сертификат готовности production-релиза.

HTTP: GET /api/config, POST /api/runs, GET /api/runs/:id,
GET /api/runs/:id/artifacts/:name. Ошибки Git/модели сохраняют evidence/trace.
Провайдер выбирается явно. Gemini получает разрешённые фрагменты исходников;
local — настроенный локальный endpoint. Автопереключения нет.

Результаты: evidence.json, analysis.json (при успехе), trace.json,
release-notes.md, test-plan.md, report.html. Запись только в runs/<UUID>.
Сырые ответы модели и персональные абсолютные пути в evidence не сохраняются.
