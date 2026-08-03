# مرجع التوقيعات الفعلية لطبقة الوعي

مُستخرج بالتفتيش المباشر (`inspect`) لا بالتخمين. الغرض منه منع
اختبارات تفشل فشلًا وهميًا لأنها تُنادي أسماء غير موجودة.

## identity
`self_model()`, `describe_self() -> str`, `purpose_statement()`,
`runtime_facts()`, `awareness_dir()`, `app_data_dir()`, `app_version()`,
`is_frozen()`, `repo_root()`
كائنات: `SelfModel`, `Capability`, `Impact`; ثوابت: `CAPABILITIES`,
`CAPABILITY_BY_KEY`, `BOUNDARIES`, `PURPOSE`, `OWNER_NAME`.

## journal
`info/warn/error/debug/fatal(event, **fields)`, `log`, `recent`,
`stats`, `capture`, `instrument`, `sanitize`, `fingerprint`,
`exception_facts`, `perf_samples`, `journal_path`, `set_sink`,
`add_exception_listener`, `install_global_hooks`.
مستويات: `DEBUG INFO WARN ERROR FATAL`.

## vitals
`full_scan(*, use_cache=True, deep_imports=True) -> HealthReport`
`quick_scan()`, `probe_import`, `find_tesseract`, `invalidate_cache`
كائنات: `HealthReport`, `Finding`, `Severity`, `Impact`, `MODEL_SPECS`.

## healer
`heal(report=None, **kw) -> HealSession`
`heal_from_exception(exc, **kw) -> RetryDecision`
`overrides(refresh=False) -> dict`
`set_override(key, value, *, reason="") -> bool`
`get_override(key, default=None)`
`healer() -> Healer`

## surgeon
`diagnose(**kw) -> list[Issue]` — الوسائط الفعلية:
`use_cache: bool = True`, `codes: list[str] | None = None`
(لا يوجد وسيط `paths`)
`operate(*, codes=None, targets=None, apply=False, max_files=12, reason="") -> SurgeryResult`
`rollback(surgery_id)`, `rollback_last()`, `history(limit=20)`, `surgery_dir()`
حقول `Issue`: `code, title_ar, detail_ar, path, line, severity, transform, context`

## dialogue
`understand(text) -> Intent`, `ask(text, *, confirmed=False, apply=True) -> dict`
`changes(limit=30)`, `undo_last()`, `normalize(text)`, `capabilities_ar()`
حقول `Intent`: `key, title_ar, kind, risk, confidence, params,
explain_ar, needs_confirmation, alternatives, raw`
**الحقل هو `key` لا `name` ولا `intent`** — خطأ شائع أوقع اختبارًا سابقًا.
`Intent.understood` = `bool(key) and confidence >= 0.35`

## perf
`record(name: str, ms: float, ok: bool = True) -> None`
`hotspots(top: int = 10) -> list[dict]`
`report_ar()`, `summary()`, `recommend()`, `promote_baseline()`,
`compare()`, `budget`, `span`, `timed`, `measure`, `memo`, `lazy`,
`parallel_map`, `persist`, `engine()`
كائنات: `PerfEngine`, `Segment`, `Advice`.

## core
`awake(**kw) -> AwakeState`, `is_awake()`, `sleep()`, `state()`,
`pulse()`, `start_pulse()`, `introspect() -> dict`, `ask(text, **kw)`,
`guard(operation, *args, name="", retry=True, **kwargs)`
→ يُرجع `(ok, result, message_ar)` ولا يرفع الاستثناء
`deep_scan`, `audit_code`, `self_improve`, `span`, `timed`,
`perf_hotspots(top=10)`, `perf_report_ar(top=5)`, `add_observer`, `mind()`

## engine_v2 (بعد إصلاحات هذه الجلسة)
`processor_v2.imwrite_unicode(path, img, lossless_webp=True, quality=None)`
`ProcessOptionsV2` حقول جديدة: `quality: int|None`, `output_format: str`
`awareness_bridge_v2.apply_overrides(opts, *, explicit=None)`
`awareness_bridge_v2.effective_overrides() -> dict`
`integration_v2._coerce_options(obj, source_path="")` — يمرّ بالجسر
