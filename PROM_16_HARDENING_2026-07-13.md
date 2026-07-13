# PROM 16 — apt-engine 고도화 리서치 (2026-07-13)

> **cycle**: `prom16-apt-engine-hardening-2026-07-13` · N=16 (4 axis × 4 lens) · 전 cell 완료
> **대상**: `PI/apt-engine` — stdlib-only KG-free 결정론 APT phase-and-gate substrate
> **축**: cognitive 우위 아닌 **operational-substrate 가치**(재현·감사·세션연속성)로 승부
> matrix: Axis A(gate 대수) / B(measured-gate trust-root) / C(detect + ManifestSource seam) / D(아키텍처 대칭·contrib 승격) × Lens 1(형식이론) / 2(OSS 선례) / 3(함정·적대) / 4(구체 처방)

---

## 0. 사전 지식 — 리서치가 밝힌 현 상태

**핵심 반전: apt-engine은 이미 상당히 단단하다.** "고도화"는 재작성이 아니라 *표적 보강*이다.

- measured gate(`precondition.py`)는 이미 run-time sha256 검증 + subprocess 격리(`-o addopts=`, `--import-mode=importlib`, `-p no:cacheprovider`, `PYTEST_ADDOPTS`/`PYTEST_PLUGINS` env scrub) 구현. `os._exit(0)` pass-위조는 `passed >= len(node_ids)` count guard로 이미 차단(B3). P2-5 실행에서 interpreter `-I`까지 추가됐다.
- KG seam(`KgManifestSource`)은 이미 fail-closed: empty rows → `ImpactSpec(required=())` → exit 4 → FAIL (vacuous PASS 아님). backend 예외 → `ValueError`이며, 리서치 당시에는 gate FAIL로 뭉개졌으나 P2-7 이후에는 could-not-evaluate `ERROR`로 분리된다. **회귀 테스트까지 존재**(`test_kg_source_empty_rows_fail_closed`) (C3).
- `ManifestSource`는 이미 `@runtime_checkable Protocol` — pluggy/entry_points 없이 stdlib DI. 업계 최선 idiom(C2).

∴ 진짜 결함은 **detect.py의 confidently-wrong 버그 + gate 대수의 미검증 불변식 + receipt 부재** 세 곳에 집중.

---

## 1. Consensus — 다수 cell 독립 수렴 (높은 신뢰)

### C1. GateReceipt emitter — **4-cell 수렴 (최강 합의: B1·B4·D1·D4)**
measured gate는 "green이면 PASS"만 하고 **감사 흔적을 남기지 않는다**. `GateResult`는 `(from, to, verdict, reason)`뿐 — 무엇이 언제 어떤 sha로 돌았는지 기록 0.
- **처방**: stdlib `json`으로 `apt_engine/receipt.py` 신설. `GateReceipt{transition, verdict, mandated_node_ids, sha256_pinned, sha256_observed, pytest_exit_code, manifest_source_kind, runner(ci|local), timestamp_utc, python_version, apt_engine_version}`. `evaluate_measured_mandated_from`에서 `GateResult`와 함께 생성(additive, 시그니처 무파괴). CLI `--receipt-out path.json` + MCP `apt_gate_measured` 응답 필드.
- **왜 최강**: ADR-0003이 자인한 정직 경계("trust me it passed" → "여기 영수증")를 정확히 메움 + `apt-engine verify --replay`의 전제 아티팩트 + **promotion checklist를 스스로 통과하는 유일한 신규 기능**(stdlib∧KG-free∧testable). SLSA/in-toto attestation(DSSE) shape 축소판. `runner=ci`는 `os.environ.get("CI")`로 stamp → "local=방어심화 / CI=신뢰" 구분을 doc이 아닌 machine-checkable로.

### C2. detect.py 건전성(soundness) 결함 — **3-cell 수렴 (C1 이론 + C3 실증 + C4 처방)**
`_current_phase()`가 **CHAIN 순서상 가장 뒤 phase 중 regex가 파일 어디서든 hit한 것**을 반환. 시간·부정·구획 인식 0.
- **C3 실증**: 모든 phase 이름을 나열한 roadmap 스타일 `apt-progress.md` + "아직 아무것도 안 함" → `current_phase="Cleanup"`을 **EXTRACTED(최고 신뢰)** 로 보고. 실제로 재현됨.
- **C1 형식화**: 건전성 불변식 = `current_phase ≠ unknown ⟹ {hit된 phase 집합} == CHAIN-prefix`(gap 없는 접두사). 위반 시 *마지막 연속 phase*만 반환 + confidence AMBIGUOUS 강등. monotonicity property test(artifact 늘면 phase 절대 후퇴 안 함).
- **부수 발견(C3)**: `feature-spans.json`은 phase 추론에 실제로 안 쓰임 → docstring의 `INFERRED` 라벨은 **dead code**. `_read_spans_file`는 TOCTOU 비안전(race 시 crash).

### C3. gate 대수 exhaustive property test — **2-cell 수렴 (A1·A4, 둘 다 HIGH)**
6-branch 우선순위와 `unlocks_downstream`이 **8개 example test로만** 검증됨. 전 입력공간 = `6×6×2×2×2 = 288` 튜플(작음 → 열거 가능).
- **처방**: **Hypothesis 금지**(stdlib-only core 유지) → `itertools.product` + `pytest.mark.parametrize`로 288 전수. `tests/test_gate_algebra_exhaustive.py` 4 함수: ① SKIP은 절대 unlock 안 함 ② PASS만 unlock ③ self-application은 flag 조합 무관 항상 FAIL(현재 test가 절대 안 섞는 조합) ④ 6-branch 우선순위를 순수함수 oracle로 인코딩 후 288 전수 일치.

### C4. verdict 어휘가 3~4개로 파편화 — **2-cell 수렴 (A1·A2)**
`gate.Verdict{PASS/FAIL/SKIP/CONDITIONAL}` ↔ `contrib/opa.OPADecision{allow:bool}`(OPA의 undefined 상태 소실) ↔ `contrib/gate_policy.OutwardVerdict{PASS/FAIL/WOULD_FAIL/OPEN_REFUSED}` + `circuit_breaker.OPEN_REFUSED` — 동형사상 문서화 0.
- **처방(reconciled)**: core `gate.py`에 **`ERROR` verdict 신설**(FAIL과 구분 — resolver/source 부재는 "평가했더니 no"가 아님). `UNKNOWN`은 ERROR와 구별되는 독립 의미·consumer가 없어 미도입/보류. 단 A2의 "opa/gate_policy를 core에 wire"는 **§2 충돌에서 기각**(D3/D4 piecemeal-promotion 함정).

---

## 2. Divergence / Conflict — 상반 결론 (해소 필요)

### Conf-1. contrib 승격: "core에 wire"(A1·A2) ✗ vs "0/6 승격 불가"(D4·D3) ✓
- A1/A2: gate_policy·opa를 core gate로 통합해 단일 상태기계.
- **D4 실측**: 6 port 전부 stdlib✓/tested✓지만 **"real consumer" 게이트 실패**(cli/mcp 어느 것도 import 안 함) → ADR-0002 CUT을 선언 아닌 *실증적으로* 정당화. `gate_override`가 가장 근접하나 call site 0.
- **D3 경고**: piecemeal 승격 = 각각은 무해해 보여도 누적되면 T2(636 LOC/43%, composition root 없음) ISP 위반 재현 + httpx/redis/neo4j를 "stdlib-only"에 끌어들임.
- **해소**: **승격 안 함(CUT 유지).** 어휘 통일이 필요하면 core `gate.py`에 `ERROR` 직접 추가 + `contrib`엔 `to_outward(v, mode)` 매핑 함수(homomorphism 증명 test). contrib→core import는 여전히 금지.

### Conf-2. compose_chain 모노이드(A1) — 신규 추가 vs YAGNI
- A1: chain 전체 verdict(`compose_chain`, PASS=항등원/FAIL=흡수원 commutative monoid).
- A1 자체 caveat + D2: **아직 multi-edge 집계를 필요로 하는 caller 없음**. speculative.
- **해소**: **EXPLORATION 보류.** MetaReview가 실제 chain-level verdict를 소비하는 concrete consumer가 생기면 그때. 지금 만들면 caller 1개짜리 추상.

### Conf-3. 형식화 깊이: bilattice/FDE(A1) vs formal-cathedral 경계(A1 자기 caveat)
- **해소**: 순수 transition의 4-state 유한 열거(PASS/FAIL/SKIP/CONDITIONAL; 측정 wrapper의 ERROR는 별도)에 full FDE 증명론 = over-formalization(프로젝트 자체 `formal-cathedral` 나생문 lens smell). SKIP=bottom/CONDITIONAL=top의 knowledge-order는 **docstring 주석까지만**, 증명론은 exhaustive property test로 대체.

---

## 3. Open Questions

- **OQ1**: env-closure attestation(B1 — conftest.py+lockfile+py 버전 sha를 `ImpactReq.env_sha256`로) = SLSA L2/L3. stdlib core냐 dgx-layer냐? (B1은 core 제안, B2/D4는 dgx 위임이 ADR-0002 경계와 정합.) → **dgx-layer 유력, OPEN.**
- **OQ2**: apt↔tpa 공유 `verdict` micropackage(D2, ~30줄) — 2번째 consumer(tpa `fitness.GateResult`) 있으나 "1 caller 넘어야 추출" 원칙과 경계선. → 지금 추출 vs 대기 OPEN.
- **OQ3**: OpenSpec delta-spec을 SP 재진입에 도입(D2) — 기존 AtomicSpan 있는 repo 재-decompose 대신 ADDED/MODIFIED/REMOVED diff. **진짜 pain case(span churn 심한 반복 cycle) 나오기 전 보류.**
- **OQ4**: CONDITIONAL follow-up 강제(A3) — stateless `evaluate_transition`엔 ledger 없음. 이 계약을 core가 질 것인가(GateLedger) vs "enforcement는 dgx runtime" 선언으로 정직화? → §4 P1-3에서 후자로 잠정.

---

## 4. 권장 후속 작업 (Action Plan)

### P1 — 지금 배포 (HIGH conf · 저위험 · 고레버리지)
1. **GateReceipt emitter** (`apt_engine/receipt.py`, stdlib json) — §1-C1. 4-cell 합의. ADR-0003 정직 경계를 메우고 replay 전제. ✅ **IMPLEMENTED 2026-07-13 (§실행로그 참조).**
2. **detect.py 건전성 수정** — §1-C2. ✅ **IMPLEMENTED 2026-07-13 (§실행로그 참조).** 근본원인=marker 검출이 bare 키워드/descriptor를 진행으로 오인. line-subject+status-required 검출로 재설계.
3. **gate.py 모순 flag guard + CONDITIONAL 정직화** — §OQ4. `if conditional and skipped: raise ValueError(...)` + stateless core의 비강제 범위를 명시. ✅ **IMPLEMENTED 2026-07-13 (§실행로그 참조).**
4. **gate 대수 288-튜플 exhaustive test** (`tests/test_gate_algebra_exhaustive.py`, stdlib parametrize) — §1-C3. ✅ **IMPLEMENTED + 보강 2026-07-13 (§실행로그 참조).**

### P2 — 싼 승리 (HIGH conf)
5. **subprocess pytest에 `-I` 격리 모드** (B3) — PYTHONPATH/sitecustomize/user-site 주입 차단 + 설치 패키지 운영계약 검증. ✅ **IMPLEMENTED 2026-07-13.**
6. **`apt-impact.json`에 CODEOWNERS** (B2) — zero-dep review routing. CODEOWNERS 자체는 병합 강제가 아니며 host ruleset이 별도 필요. ✅ **IMPLEMENTED 2026-07-13.**
7. **`ERROR` verdict 추가** (§1-C4, A2) — source/resolver 부재를 FAIL로 뭉개지 않기. core 직접 추가(contrib 승격 아님); `UNKNOWN`은 별도 의미 부재로 보류. ✅ **IMPLEMENTED 2026-07-13.**
8. **`.importlinter` forbidden + adapter-independence 계약, promotion checklist, "gate PASS = 필요조건이지 충분조건 아님" README 한 줄** (D3·D4). full `layers`는 실제 의존 cycle 때문에 미채택. ✅ **IMPLEMENTED 2026-07-13.**

### P3 — 설계 (EXPLORATION · real consumer 게이트)
9. **`ChainedManifestSource` + richer `PhaseReport` (`blockers`)** (C4) — ⏸ **DEFERRED_NO_CONSUMER (2026-07-13)**. 두 제안을 독립적으로 실측했으나 shipped decision-making consumer가 없었다. `ChainedManifestSource`는 실제 composition root/caller가 없고, detect CLI/MCP는 현재 report를 직렬화·전달할 뿐 blocker 레코드에 따라 행동하는 caller가 없다. concrete consumer와 테스트가 생길 때 재개한다. (`http_kg_client`/`neo4j_kg_client`는 `KgManifestSource`의 transport이지 별도 `ManifestSource` 단계가 아니다.)
10~13. §OQ1~OQ4 (env-closure sha / 공유 verdict micropackage / SP delta-spec / GateLedger) — 조건 충족 시.

### ✗ 하지 말 것 (적대 cell이 명시 차단)
- **contrib port를 core로 승격** (D4: 0/6 통과, D3: piecemeal 함정). `kg_manifest`/`resolver`는 KG/Jinja 결합이라 **consumer 생겨도 영구 opt-in**.
- **gate_policy/opa를 core gate에 wire** (A1/A2 제안 → D3/D4로 기각).
- **full FDE 증명론** (formal-cathedral smell).
- **cognitive uplift 주장** (D1 guardrail — README/AGENTS.md에 "추론 품질 측정 아님" 명문화).

---

## 부록 — 16 cell provenance
A1 gate/formal(MED) · A2 gate/industry(MED) · A3 gate/pitfalls(HIGH) · A4 gate/prescription(HIGH) · B1 trust/formal(HIGH) · B2 trust/industry(MED) · B3 trust/pitfalls(HIGH) · B4 trust/prescription(HIGH) · C1 detect/formal(MED) · C2 detect/industry(HIGH) · C3 detect/pitfalls(HIGH) · C4 detect/prescription(MED) · D1 arch/value(HIGH) · D2 arch/symmetry(MED) · D3 arch/pitfalls(HIGH) · D4 arch/prescription(HIGH)

> ⚠️ 정직 표기: 본 리포트는 AI 리서치 종합(주석)이지 사용자 verdict(정전) 아님. 이 문장은 리서치 완료 시점의 경계였고, 이후 user trigger로 P1/P2와 P3 consumer audit가 실행됐다. 현재 상태는 아래 실행 로그가 권위적이며 P3-9는 `DEFERRED_NO_CONSUMER`, 나머지 open question은 미구현 제안이다.

---

## 실행 로그

### P1-1 GateReceipt emitter — ✅ IMPLEMENTED (2026-07-13, user trigger "1번 진행")

**구현**: 6 파일 (OMD lease HELD 하에 편집).
- **NEW `src/apt_engine/receipt.py`** (stdlib-only) — `GateReceipt` frozen dataclass + `build_gate_receipt()` + `runner_kind()` + `audit_key()`. `RECEIPT_SCHEMA_VERSION="apt-engine/gate-receipt/v1"`. 필드: transition/verdict/gate_kind/reason/gate_version/target/manifest_source_kind/mandated·matched_node_ids/sha256_pinned·observed/pytest_exit_code/evidence_source/runner(ci|local)/timestamp/python_version/apt_engine_version/error.
- **`precondition.py`** — `PreconditionEvidence`에 `matched_node_ids`+`observed_shas`(optional, default-empty) 추가; `measure_mandated`가 관측 sha(**node_id 키** — pinned와 조인 가능·checkout 이식)+matched 누적; `evaluate_measured_mandated_from`을 `*_with_receipt`로 delegate(**behavioral 동일** — regression 렌즈 0 findings로 확증); `*_default_with_receipt` × 2 신설.
- **`cli.py`** — `--receipt-out PATH` (mandated/bare/asserted 3경로 모두 receipt JSON).
- **`mcp_server.py`** — `apt_gate_measured` 응답에 `"receipt"` 키.
- **`__init__.py`** export + **`.importlinter`** receipt 등록.
- **`tests/test_receipt.py`** — 23 신규 테스트.

**검증**: `165 passed` (전 스위트) / `ruff clean` / `import-linter KEPT`(core→contrib 불변식 유지) / 실제 dogfood(repo 자체 `apt-impact.json`) green PASS + drift NONE(pinned==observed by node_id).

**적대적 리뷰**(5렌즈×find+verify 워크플로, 11 confirmed): **regression=0**(delegation 안전). 수정 반영:
- **audit_key 이식성 버그** (MEDIUM) — 절대경로(target/matched abs/observed 키/evidence_source)가 섞여 checkout마다 false-drift → observed를 node_id 키로 전환 + audit_key에서 machine-specific 필드 제거. `test_audit_key_is_checkout_portable`로 잠금.
- **bare 경로 exit code 유실** (LOW) — `evaluate_measured_default_with_receipt` 신설로 실제 pytest exit code 기록.
- 문서 정밀도(hashable→audit_key / 제외필드 열거 / runner=ci 자기주장 caveat) + import-linter 등록 + 테스트 갭(red-with-matched / bare·asserted / multi-req 정렬).

**미결(defer)**: **commit/push** — `PI/apt-engine`는 `GIT/delltower_import`의 `.git` 제외 스냅샷 심링크(SYMPOSIUM gitignored). 실제 push는 apt-engine 원격 clone 필요 → blocker. 로컬 편집·검증은 완료.

### P1-2 detect.py 건전성 수정 — ✅ IMPLEMENTED (2026-07-13, user trigger "이어서")

**버그(실증 재현)**: `detect_phase`가 phase 키워드 정규식이 파일 어디서든 hit하면 진행으로 취급 → 모든 phase 이름을 나열한 로드맵 문서 + "아직 아무것도 안 함"이 `current_phase=Cleanup`을 `EXTRACTED`(최고신뢰)로 보고.

**근본원인(2라운드 적대 리뷰가 규명)**: 내 1차 시도(saturation guard — 전 phase/양 terminal 나열 시 unknown)는 **증상패치**였다. 리뷰가 실제 근본원인 적발 = terminal 정규식(MetaReview/Cleanup)이 status 동사 없이 **bare 키워드**("cleanup"/"ratchet"/"Meta-Review")만으로 phase 날조(HIGH, 흔한 단어라 trivially 발동). 2차 시도(status-required proximity)도 negation("SA not complete")·mid-sentence("the SP diagram complete"/"CI ratchet passed"/"St. Louis complete")에 오탐 → **line-subject 앵커링**으로 수렴.

**최종 구현** (`_detect_markers`, line-based): 한 줄이 phase를 marking하려면 (1) phase 이름이 **줄의 주어**(markdown bullet/heading/checkbox 뒤 시작), (2) 그 줄에 **STATUS 동사**(complete/in-progress/done/passed), (3) status 앞에 **negation/future 없음**(not/no/will/later/planned…). + SA/SP/ST/SCW **대소문자 구분**(St. 충돌 차단). 부수효과로 옛 dead `ST crystalliz\b` 정규식도 해결.
- **contiguity 체크**(C1 명령, 내가 1차에 누락): forward-leap(gap 뒤 late phase)→ 가장 먼 gap-free phase + AMBIGUOUS.
- **saturation guard**(방어심화): 전 phase/양 terminal → unknown.
- **TOCTOU 가드**(progress/spans read OSError→degrade) + `_empty_report` `spans_summary` 키 통일 + `INFERRED` reserved 명시.

**검증**: `182 passed`(전 스위트) / `ruff clean` / `import-linter KEPT` / 재현 falsifier 닫힘 + 리뷰의 6개 오탐 케이스 전부 통과 + edge(bullet 변형/blockquote/word-boundary/CRLF/heading) 자체검증. `tests/test_detect.py` 22 test.

**2라운드 적대검증 결산**: contiguity·regression 렌즈 = 0 findings(로직·소비자 안전). new-regex-edges = proximity의 정밀도 6건(negation/EXTEND/mid-line ratchet/거리제한/좌표오탐/St.) 전부 line-based 수렴으로 해소. **패턴: 매 라운드 리뷰가 내 fix의 다음 결함을 산출 → 3-iter로 근본 해결.** [[lesson-apt-detect-status-required-marker-2026-07-13]]

**미결(defer)**: commit/push (P1-1과 동일 blocker — 스냅샷 심링크, 원격 clone 필요).

### P1-3 gate 모순 flag guard + CONDITIONAL 정직화 — ✅ IMPLEMENTED (2026-07-13, user trigger "쭉쭉 진행")

**상태 반전**: 실태 확인 결과 P1-3 코어(`if conditional and skipped: raise ValueError`가 precedence step 0, phase 이름 resolution *前*)와 CONDITIONAL 정직화(docstring 명시 — stateless core는 follow-up VR 강제 못 함)는 **이전 세션에 이미 구현**됨. CLI도 `add_mutually_exclusive_group()`로 exit 2 처리. 이번 세션 = 적대검증 + 정밀화.

**적대검증**(5-lens find × 발견당 3-refuter 워크플로, 50 agents): 1 CONFIRMED / 14 refuted. (docstring-honesty 렌즈 검증자 5개는 크레딧 소진으로 불발 → 직접 확인.)
- **CONFIRMED (MEDIUM, oracle-independence)**: 288-전수 스위프가 verdict만 검증하고 **FAIL의 `gate_version` 값**은 미검증. 뮤테이션 실증 — 어느 FAIL 분기에서 `dst.gate_version_on_fail` 인자를 지워도 192 전부 green. `test_gate_version_only_on_fail`이 한 방향(non-FAIL⇒None)만 봤음. → **수정**: `test_gate_version_iff_fail_and_reason_always_set`로 양방향화 (FAIL ⇒ gate_version == 목적지 canonical 값 + 모든 verdict에 reason non-empty). 재현 뮤테이션이 이제 잡힘(실측).
- 직접 확인한 docstring-honesty 잔존: **ADR-0001 line 44**가 아직 "CONDITIONAL requires a follow-up VR"을 gate.py 제공 기능처럼 서술 → stateless-core 미강제 명시 + ERROR 반영으로 정정.

### P1-4 gate 대수 288-튜플 exhaustive test — ✅ (이전 세션 구현) + 보강 (2026-07-13)

`tests/test_gate_algebra_exhaustive.py` = 288 전수(72 contradictory raise + 216 oracle 대조) 이미 존재. 이번 세션 보강 2건: ① 위 CONFIRMED의 gate_version 값 검증 추가 ② `test_pure_transition_never_returns_error_across_all_valid_tuples` — 순수 `evaluate_transition`은 ERROR 절대 미반환(ERROR는 측정 wrapper 전용) 불변식 pin.

### P2 — 싼 승리 4건 ✅ IMPLEMENTED (2026-07-13)

- **P2-7 `ERROR` verdict** (§1-C4/A2): `gate.Verdict.ERROR` 신설 — **could-not-evaluate**(manifest 판독불가/source backend 예외 = "무엇을 측정할지조차 모름")를 **evaluated-to-no**(FAIL)와 분리. `precondition.py`의 outer `except`(OSError/JSONDecodeError/ValueError/TypeError)만 ERROR로 승격; 측정 *中* 발견된 missing/sha-drift/unhashable mandated test는 exit code로 FAIL 유지(정밀 경계). `can_advance(ERROR) is False` — fail-closed·CLI exit 동작 무변. 순수 `evaluate_transition`은 ERROR 미반환. MCP `hades_realizes_by_verdict` 테이블을 enum 전수로(ERROR 포함). 영향 테스트 5건(kg_manifest backend-down / receipt unevaluable / impact-binding missing-manifest / manifest-source source-error / receipt-build unit) FAIL→ERROR 정정.
- **P2-5 `-I` 인터프리터 격리** (B3): 세 측정 subprocess(`pytest_runner`/`pytest_collector`/`pytest_id_runner`) argv에 `python -I` prepend — PYTHONPATH/user-site/CWD sys.path[0] 주입 차단. **운영계약 실측**(dogfood): editable 설치된 gated 패키지는 -I에도 해석되나 `PYTHONPATH=src`류 미설치 경로는 안 됨 = CI gate 정론(설치 아티팩트 측정). repo 자체 apt-impact.json dogfood = **PASS / exit 0 / 양 mandated 매칭 / drift NONE** 실측.
- **P2-6 `CODEOWNERS`**: measured gate trust-root(`apt-impact.json` + `/src/apt_engine/` + `/tests/` + root pytest/build config + CI/import 계약/CODEOWNERS) owner-review routing. 실제 required review는 host ruleset/branch protection 책무.
- **P2-8 promotion checklist + `.importlinter` 보강 + README 한 줄**: `docs/PROMOTION_CHECKLIST.md`(6-gate, 0/6 통과 근거) + `.importlinter`에 `independence` 계약(detect/phase_map/legion 병렬 어댑터 상호 미import; 전 `layers`는 receipt.py TYPE_CHECKING back-import cycle로 의도적 미채택) + README "gate PASS = 필요조건이지 충분조건 아님".

**검증**(복구된 production venv, python 3.14.6 editable): **194 passed** / **ruff clean** / **import-linter 2 kept, 0 broken** / measured-gate dogfood PASS.

**환경 사고 + 복구**(2026-07-13): 세션 中 `~/.local/share/uv/python/` 전체가 purge돼(디스크 압박 추정) apt-engine 포함 **PI 워크스페이스 全 venv가 dangling**(3.12·3.13 인터프리터 소멸) + uv 바이너리 소실. 복구: ①시스템 3.9로 코드 import 가능 확인(annotations-only 3.10+) → scratchpad 3.9 verify venv(pytest 7)로 1차 검증 ②`pip install --user uv`로 uv 복구(0.11.28) → `uv sync`로 apt-engine production venv 재구축(3.14.6 + deps + editable). **잔존**: sibling venv(lakatotree/ooptdd/omd/bhgman_tool)는 각자 `uv sync` 필요 — 미실행.

### Codex closeout 검증 — ✅ (2026-07-13)

- ERROR/포트 수/import 계약/CODEOWNERS 강제성의 문서 드리프트를 실제 코드·host 능력에 맞춰 정정. CODEOWNERS는 일부 파일 열거가 아니라 measured run에 영향을 주는 `/src/apt_engine/`, `/tests/`, root pytest/build config, CI 전체를 owner-review로 routing한다(실제 required review는 host ruleset 필요).
- 회귀 5건 추가: 세 production pytest subprocess의 `python -I` 접두사, PYTHONPATH `pytest.py` fake-green 공격, CLI/MCP ERROR+receipt 직렬화, import-linter core-module 열거 완전성.
- 신선한 `gj3447/apt-engine` clone + editable Python 3.14.6 환경에서 **199 passed** / **Ruff clean** / **import-linter 2 kept, 0 broken** / `git diff --check` clean.
- measured-gate dogfood: **PASS / exit 0 / mandated 2개 모두 matched / pinned sha == observed sha / error null**.

**출판 경로**: `GIT/delltower_import` 스냅샷의 `.git` 부재 blocker는 canonical `gj3447/apt-engine` fresh clone으로 검증된 소스만 선별 이식해 해소. landing branch는 `agent/apt-engine-hardening`이며 draft PR로 review한다. `.claude`/SYMPOSIUM·venv/cache/build는 이식하지 않았고, base PR #1에서 이미 추적된 `uv.lock`은 이 closeout delta가 수정하지 않는다.

**출판 완료 (2026-07-13)**: [PR #2](https://github.com/gj3447/apt-engine/pull/2)는 `main`에 squash-merge됐으며 merge commit은 `33f0de558ac088c8729b0d53972ccfbbf8a58f7c`다. P1/P2 publication status는 `MERGED`.

### P3-9 real-consumer audit — ⏸ DEFERRED_NO_CONSUMER (2026-07-13)

- **Manifest branch**: shipped fallback caller/composition root가 없다. source precedence, authoritative-empty, source-error fallback 정책도 결정되지 않았으므로 API/code를 추가하지 않았다. 현재 계약은 `FileManifestSource` 또는 `KgManifestSource`; HTTP/bolt는 후자의 transport다.
- **Detect branch**: 실제 public 이름은 `DetectResult`가 아니라 `PhaseReport`. CLI/MCP는 report를 그대로 출력/반환하지만 `blockers`에 따라 결정을 바꾸는 shipped consumer가 없어 API/code를 추가하지 않았다.
- **재개 조건**: concrete shipped consumer, failure semantics, end-to-end tests가 함께 제시될 것.

> **권위 경계**: repository measurement에 근거한 implementation triage (`SECONDARY_AI`)이며 사용자 정전 verdict가 아니다. 사용자 continuation trigger는 조사를 승인했지만 이 설계안을 정전화하지 않는다.

### P3 audit side-finding — measured-wrapper preflight ordering ✅ IMPLEMENTED (2026-07-13)

P3-9 구현과 별개로, measured-wrapper family가 pure gate precedence를 외부 I/O 전에 일관되게 적용하지 않는 기존 결함을 발견했다. private optimistic preflight가 8개 public measured API의 직접 또는 위임 경로에 적용된다. caller bug와 unknown phase는 external I/O 전에 raise하고, structural `FAIL`과 `SKIP`은 manifest/file/KG/source/collector/runner/pytest를 전혀 호출하지 않고 반환한다. `CONDITIONAL`과 정상 measurable transition은 실제 측정을 정확히 한 번 수행하며, production 6개 API의 known-valid non-measurable `FAIL`도 유지한다.

**TDD·검증**: 변경 전 지정 falsifier 4건이 정확히 실패했다(선행 runner, unknown phase의 generic FAIL 흡수, 선행 collector, source `ValueError`의 `ERROR` 흡수). 구현 후 신규 계약 **47 passed**, 관련 회귀 **149 passed**, 전 스위트 **246 passed**. Ruff/format, `git diff --check`, import-linter **2 kept / 0 broken**, `complexipy --diff origin/main --ratchet --max-complexity-allowed 10`을 모두 통과했다.

**Cleanup/적대 검증**: deterministic Cleanup gate는 **5/7 `NEEDS_REFACTOR` (non-blocking)**. delta ratchet은 Lizard max NLOC **67=67**, Pylint duplicate-code **2=2**, vulture **2=2**, fat-file count **2=2**, import-linter **2 kept / 0 broken**으로 기준을 회복·유지했다. 반면 기존 deptry **11=11**은 절대 0 기준을 못 넘고, 최근 14일 conventional refactor:feature 증거도 **0/0**이라 두 축은 실패했다. `tach.toml`이 없어 import-linter를 ADP 대체 증거로 사용했다. 후속 debt는 KG `refspec-apt-engine-p3-consumer-gate-2026-07-13`에 OPEN으로 기록했다. 서로 다른 executor context의 두 리뷰와 Claude Sonnet fulfillment review가 blocker 0으로 승인했다. 리뷰가 찾은 8-entry caller-bug matrix 공백과 receipt docstring 경계는 즉시 보강했고, pure delegation의 중복 preflight 1회는 관측 가능한 동작이나 I/O가 없어 atomic scope 밖 cleanup 후보로 남겼다.

> **분류**: deferred P3 feature 구현이 아니라 기존 gate semantics의 ordering/conformance 수정이다.
