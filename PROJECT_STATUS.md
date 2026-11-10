# SignOffAI 鏋舵瀯鐜扮姸涓庝慨澶嶆姤鍛婏紙2026-11-10锛?
> 鍒嗘瀽瀵硅薄锛歚C:\Users\liujiangqing\Desktop\cdv_advanced`
> 褰撳墠鍒嗘敮锛歚refactor/langgraph-migration`
> 淇鑼冨洿锛氶櫎 `isa_ir_tools` / TB player 涓?EDA 渚濊禆澶栫殑宸茬煡闂
> 杈圭晫锛氭湰鏈烘病鏈?QuestaSim 涓?LLM key锛汦DA/LLM 璺緞鏈疄娴嬨€?
---

## 0. 缁撹

**鏈淇鎶娾€滄灦鏋勫師鍒欐纭€佷絾娴嬭瘯/legacy/鏂囨。/瀹夊叏娌℃敹鍙ｂ€濈殑鐘舵€佹敹鍙ｅ埌浜嗗彲鎻愪氦銆佸彲鍥炲綊鐨勫熀绾匡細涓诲浠朵笌宸ヤ綔鍙板浠跺潎鏃?failed锛屾灦鏋勫畧鍗€氳繃锛宐oards/legacy/鏂囨。閾炬帴/鏄庢枃鍑嵁宸叉竻鐞嗭紝VPlan 鐨?gate 閫?run 涓?active 婕傜Щ銆乀P realization銆佺煩闃?schema銆乽vm_arch 鏄犲皠涔熷仛浜嗗寮恒€?*

浠嶆湭闂幆銆佷笖鎸夎姹備笉淇殑涓ら」锛?
1. `isa_ir_tools` / TB player 鐨勯泦鎴愪笌鑷姩鍖栨祴璇曪紙鐙珛宸ュ叿锛屾寜浣犵殑瑕佹眰璺宠繃锛夈€?2. 闇€瑕?QuestaSim 鐨?VPlan 鐪熷疄 E2E锛堟寜浣犵殑瑕佹眰璺宠繃 EDA 鐩稿叧闂锛夈€?
鍥犳褰撳墠鐘舵€佸簲琛ㄨ堪涓猴細

> **鈥滄灦鏋勪笌宸ョ▼鍩虹嚎宸叉敹鍙ｏ紱VPlan 瑙勫垝灞傚彲 build銆佸彲瀹￠槄锛涚湡瀹?EDA 闂幆浠嶉渶鍦ㄨ Questa 鐨勬満鍣ㄤ笂璺戜竴杞€傗€?*

### 0.1 褰撳墠楠岃瘉缁撴灉

| 椤?| 缁撴灉 |
|---|---|
| 涓诲浠?| **1174 passed / 0 failed / 4 skipped** |
| 宸ヤ綔鍙?| **692 passed / 0 failed**锛坄QT_QPA_PLATFORM=offscreen`锛涙湁 PySide6 鍥炶皟鏋愭瀯 warning锛屾棤澶辫触锛?|
| 鏋舵瀯瀹堝崼 | `[architecture] OK` |
| 缂栬瘧妫€鏌?| `compileall` 閫€鍑虹爜 0 |
| secret scan | `scripts/check_secrets.py` 鈫?clean |
| VPlan status | `specs/npu_sched` 鍙锛?6 req / 43 features / 46 contracts / 46 TP / 20 cases |
| VPlan build | PLAN_ONLY 鎴愬姛锛沗signable=false` |
| VPlan gate | 46 contracts 鍏?`assume`銆?6 blocked銆? eligible锛堟棤 linked run锛?|
| VPlan execute | 鏈闃呴」鐩 review gate 鎷掔粷锛沝ry-run 姝ｅ父 |
| ISA IR 鍐掔儫 | 涓夐樁娈?30 涓枃浠讹紝閫€鍑虹爜 0锛堟湭绾冲叆鏈淇锛?|

---

## 1. 鏋舵瀯鍘熺悊锛堜慨澶嶅悗浠嶇劧鏄繖濂楋級

### 1.1 浜斿眰 + 24 鑺傜偣 + 8 鎵ц鍣?
```text
CLI / Workbench
  鈫?app/services
  鈫?L2 LangGraph锛?4 鑺傜偣锛?2 pure + 12 agent锛?  鈫?8 涓?executor锛坒ront/design/model/verify/ops/coverage/debug/audit锛?  鈫?L1 / L3 / L4 / L5
  鈫?core锛圧unContext / ArtifactStore / EventStore / Provenance / Quality锛?```

- 浜斿眰鏄兘鍔涘钩鍙帮紝24 鑺傜偣鏄帶鍒舵祦锛? 鎵ц鍣ㄦ槸瑙掕壊锛涗笁鑰呮浜ゃ€?- 鍙湁 `design` / `debug` 鐩存帴璋?LLM锛涙墍鏈?LLM 璋冪敤璧?`call_llm`锛屾祦绋嬩笌 pass/fail 淇濇寔纭畾鎬с€?
### 1.2 濂戠害鏄瀯寤虹墿

| 濂戠害 | 鍥炵瓟 | 鏉冨▉钀界偣 |
|---|---|---|
| dplan | RTL/鍙傝€冩ā鍨嬫€庝箞瀹炵幇 | `<run>/inputs/dplan/` + `contract/dplan_map.json` |
| VPlan `C-*` | 璇ラ獙璇佷粈涔堛€侀獙鏀朵緷鎹?| `specs/<module>/data/contract_matrix/*.csv` |
| Case IR 鍥涢泦鍚?| 鐢ㄤ緥鐢ㄤ粈涔堣瘉鏄庤嚜宸?| `<run>/coverage/case_ir.json` |
| Contract OS v3 | 姣忔潯涔夊姟鐜板湪浠€涔堢姸鎬?| `<run>/contract/{contract.yaml,obligations.json}` |
| IP release | IP 渚涘簲鏂?SoC 娑堣垂鏂圭粦瀹?| `spec/ip_releases/<ip>.json` |

### 1.3 瑙勫垝灞備笌鎵ц灞傚垎绂?
```text
spec 鈫?front bootstrap 鈫?docs/specs + data + cases
     鈫?浜哄伐 review锛堝搱甯岀粦瀹氾級
     鈫?vplan build锛圥LAN_ONLY锛歍P/Case/濂戠害锛屾棤 EDA锛?     鈫?vplan execute锛堝鐢?verify 鍐呮牳锛歎VM/鍥炲綊/瑕嗙洊鐜?璇佹嵁锛?     鈫?vplan link 鈫?vplan gate 鈫?signoff
```

- `PLAN_ONLY` 鏄庣‘涓嶅彲绛炬牳锛?- 鏈闃?杩囨湡椤圭洰锛宍vplan execute` 涓?`vplan gate --apply` 浼氭嫆缁濓紱
- 濂戠害 `assume 鈫?active` 鍙敱璇佹嵁 gate 鎺ㄨ繘锛屼笉闈犳墜鏀?CSV銆?
### 1.4 璇佹嵁椹卞姩涓庡け璐ュ搷浜?
- TP锛歚planned 鈫?HIT/OBSERVED/BACKDOOR_HIT` 鍙敱 run 璇佹嵁鎺ㄨ繘锛?- case锛歚planned 鈫?executed` 鍙敱閫愮敤渚嬭瘉鎹帹杩涳紱
- 涔夊姟锛歚PROVEN / PARTIAL / MISSING / PENDING_BACKEND / NOT_APPLICABLE / NOT_EXECUTED`锛?- 缂?EDA 鈫?`EDA_MISSING` / `BLOCKED_EDA_MISSING`锛涚己鏃ュ織 鈫?`NO_EVIDENCE`锛?- `None 鈮?False`锛宍planned 鈮?covered`锛宍assume 鈮?active`銆?
### 1.5 `sv/` 璧勪骇甯冨眬涓庨敋鐐?
```text
<run>/sv/
鈹溾攢鈹€ interface/ agents/ env/ seq/ test/ tb/ vc/
鈹溾攢鈹€ checkers/ scbs/ svas/ covgs/ cons/
鈹斺攢鈹€ asset_registry.csv
```

姣忎釜鏂囦欢甯?`ARTIFACT / SOURCE / CONTRACT_REFS / CASE_ID / STATUS` 閿氱偣锛沗package-assets` 鏁寸悊銆乣scan-assets --check` 鏍稿銆?
---

## 2. 鏈淇娓呭崟

### 2.1 娴嬭瘯涓庡畧鍗?
| 闂 | 淇 |
|---|---|
| `verify/main.py` 626 琛?> registered 600 | 鎶婃帴鍙ｆ姇褰卞嚱鏁版媶鍒?`src/executors/verify/steps/interface_spec.py`锛宮ain 闄嶅埌 522 琛?|
| `architecture_guard` 鍙湪 >2000 鏃舵鏌?registered | 鏀逛负 watched 鏂囦欢濮嬬粓鎵ц `registered` 棰勭畻锛沢uard 涓庢祴璇曞悓婧?|
| `test_tools_boards` 2 椤瑰け璐?| `boards.py` 鎸夊疄闄呯洰褰曢噸寤猴紱`generation/__init__` 鏀逛负浠?boards 娲剧敓 |
| `test_vplan_bootstrap` 2 椤瑰け璐?| 濂戠害璁℃暟鏀逛负鈥? 鍔熻兘 + 1 鎺ュ彛缁?= 3鈥濓紝娴嬭瘯鍚屾 |
| `test_staged_regression` 鏃堕棿鎴?flaky | 娴嬭瘯鏄惧紡璁剧疆 expand 鐨?mtime锛屼娇鍏剁‘瀹炴棭浜?plan |
| `test_cli_evidence` 渚濊禆浠撳簱鍐?tmp | 娴嬭瘯鐩存帴 monkeypatch `_git_changed_files` 杩斿洖 None锛屾祴鐩爣鍒嗘敮 |
| 鏃?casemodel/isa_gen/verification_os 绌哄３ | 鍒犻櫎绌虹洰褰曘€乸ycache銆乣archture.md` 0 瀛楄妭鏂囦欢 |
| 涓诲浠?| 浠?7 failed 鏀舵暃鍒?**1174 passed / 4 skipped** |
| 宸ヤ綔鍙?| 692 passed锛堝師 5 failed 鏄祴璇曢『搴?鐘舵€佹薄鏌擄紝閲嶈窇宸叉秷澶憋紱CI deselect 宸茬Щ闄わ級 |

### 2.2 瀹夊叏

- 閲嶅啓 `TODO.md`锛氬垹闄ゅ叏閮ㄧ幆澧冨彉閲?鍑嵁鍐呭锛屾敼鎴愮湡姝ｇ殑鎶€鏈€哄叆鍙ｃ€?- 鏂板 `scripts/check_secrets.py`锛氭壂鎻?git tracked 鏂囦欢涓殑楂樼疆淇?token 鍓嶇紑锛汣I lint job 涓?pre-commit 璋冪敤銆?- `SECURITY.md` 鏀逛负鈥滃綋鍓嶆爲鎵弿 + 鍘嗗彶娉勯湶闇€杞崲/娓呭巻鍙测€濈殑鍑嗙‘琛ㄨ堪銆?- 褰撳墠宸ヤ綔鍖?secret scan clean銆?
> 鍘嗗彶鎻愪氦閲屼粛鍙兘瀛樺湪鏃?token銆?*杞崲鍑嵁 + `git filter-repo` 娓呭巻鍙?*闇€瑕佸閮ㄦ搷浣滀笌 force push锛屾湰娆℃湭鑷姩鏀瑰啓鍘嗗彶銆?
### 2.3 鏂囨。涓?legacy

- `README.md`锛氱Щ闄ゅけ鏁堢殑 `docs/design` / `docs/notes` 閾炬帴涓庡凡鍒犻櫎鐨?`case-model` 鍛戒护锛涙枃妗ｅ叆鍙ｆ敼涓?ARCHITECTURE / CONTRACT_FLOW / PROJECT_STATUS銆?- `ARCHITECTURE.md`锛氭洿鏂板熀绾挎棩鏈熶笌娴嬭瘯鏁板瓧锛涘伐鍏锋澘鍧楄〃/鍖呰〃/鏂囦欢鍦板浘鏀逛负瀹為檯鐩綍锛涗慨姝?regression_tools銆乧ase_view 绛夎矾寰勶紱鏍囨敞鍘嗗彶 E2E 浜х墿涓嶅彲澶嶆牳銆?- `src/tools/README.md`锛氭寜瀹為檯 7 涓澘鍧椾笌褰撳墠鍖呴噸鍐欍€?- `known_limitations`锛歱layer 杈圭晫鏀逛负鈥淪V 鍖呭凡瀹炵幇锛屼絾 stimulus_plan/verify 涓婚摼灏氭湭鎺ョ嚎鈥濄€?- 鎭㈠ README 缂哄け鐨勫伐浣滃彴鎴浘 `docs/images/workbench-overview.png`銆?- 鍒犻櫎 `docs/濂戠害/vplan.md` 0 瀛楄妭鍗犱綅銆?
### 2.4 VPlan 澧炲己

| 澧炲己 | 瀹炵幇 |
|---|---|
| gate 閫?run 涓嶅啀渚濊禆 append 椤哄簭 | `link_run` 鍐?`linked_at`锛沗_latest()` 鎸夋椂闂村彇鏈€鏂?|
| active 婕傜Щ鍙 | `_evaluate_contract` 澧炲姞 `active_drift`锛沗vplan gate` 杈撳嚭 `active_unsupported` 骞朵互 exit 1 鎻愮ず |
| TP realization 鍙樉寮忕粦瀹?| VPlan 琛屾敮鎸?`realization_kind` / `stimulus_field` / `realization_agent` / `realization_sequence`锛涘彧鏈夋枃瀛楁椂浠嶄繚鎸?observe |
| 濂戠害鐭╅樀 schema | `_load_matrix` 鏍￠獙 13 鍒椾笌 `assume/active/exempt` 鐘舵€侊紱闈炴硶鎵嬫敼鐩存帴鎶ラ敊 |
| CSV 鍘熷瓙鍐?| `apply_active` 鏀圭敤 `atomic_write_text`锛岄伩鍏嶅崐鎴煩闃?|
| uvm_arch 绮剧‘鏄犲皠 | scoreboard 鍏堟寜 `check_artifact/object` 缁戝畾锛涙棤澹版槑鎵嶅洖閫€鍏ㄩ儴 func/data |
| 娴嬭瘯 | 鏂板 latest/drift銆佺煩闃?schema銆乀P realization 涓夌粍鍥炲綊娴嬭瘯 |

---

## 3. 浠嶇劧瀛樺湪鐨勮竟鐣岋紙璇氬疄鏍囨敞锛?
| 杈圭晫 | 鐘舵€?| 璇存槑 |
|---|---|---|
| VPlan 鐪熷疄 E2E | 鏈棴鐜?| `specs/npu_sched` 鏈闃呫€佹棤 linked run锛涢渶 Questa 鐜鎸?`review 鈫?execute 鈫?link 鈫?gate` 璺戜竴杞?|
| `isa_ir_tools` / TB player | 鏈慨锛堟寜瑕佹眰锛?| 宸ュ叿鍙啋鐑燂紝浣嗘棤浠撳簱鍐呮祴璇曘€佹湭鎺?VPlan execute/verify 涓婚摼 |
| 鍘嗗彶 secret | 閮ㄥ垎淇 | 褰撳墠鏍戝凡娓呴櫎锛涘巻鍙?token 闇€杞崲 + 鍘嗗彶娓呯悊 |
| review 绮掑害 | 淇濇寔鐜扮姸 | 浠嶅搱甯?`docs/specs + data + cases` 涓夊潡锛涚敓鎴愯祫浜у彉鏇翠細浣垮闃呰繃鏈燂紝鍚庣画鍙媶 reviewed source / generated sidecar |
| `sv/` 涓?legacy 鍙屽竷灞€ | 淇濈暀杩佺Щ寮€鍏?| `SIGNOFFAI_UVM_LAYOUT` / `--keep-legacy` 浠嶅瓨鍦紱闀挎湡搴旀敹鏁涗负 `sv/` 鍗曞竷灞€ |
| 澶氬悗绔?/ IP 瑕嗙洊鐜?/ SoC v2 | 鏈彉 | 浠嶆寜 `known_limitations` 鐨?open 椤规帹杩?|
| LLM / EDA 璺緞 | 鏈疄娴?| 鏈満鏃?Questa/LLM key |

### 3.1 褰撳墠 VPlan 瀹炴祴璇绘暟

```text
specs/npu_sched:
  requirements 26 / features 43 / topics 10
  contracts 46锛坅ssume 46锛?  testpoints 46锛坧lanned 46锛?  cases 20锛坧lanned 20锛?  review: false锛坉ocs_specs/data/cases 鏈闃咃級
  gate: 46 blocked / 0 eligible / 0 changed
```

`vplan build` 鍙敓鎴?PLAN_ONLY锛沗vplan execute` 闈?dry-run 琚?review gate 鎷掔粷锛沝ry-run 姝ｅ父銆傝繖璇存槑闂ㄧ鏄椿鐨勶紝涔熻鏄?*褰撳墠杩樻病鏈夆€滃凡楠岃瘉鈥濈殑 VPlan run**銆?
---

## 4. 涓嬩竴姝ュ缓璁?
### P0锛堝彂甯冨墠锛?
1. 杞崲鍘嗗彶涓彲鑳芥硠闇茬殑 token锛屽苟涓庡崗浣滆€呭崗璋?`git filter-repo` 娓呭巻鍙插悗 force push銆?2. 鍦ㄨ Questa 鐨勬満鍣ㄤ笂璺戜竴娆″畬鏁?VPlan E2E锛?   `review 鈫?build 鈫?execute 鈫?link 鈫?gate 鈫?evidence verify`銆?3. 鎶?E2E 鐨?commit hash / spec_hash / run_id / package_hash 鍐欒繘鍙戝竷璇存槑銆?
### P1锛?鈥? 鍛級

1. review 绮掑害鎷嗗垎锛歳eviewed source 涓?generated sidecar 鍒嗗紑銆?2. VPlan TP realization 浠?`data/dimensions.csv` 鑷姩鍥炲～锛屽噺灏戔€滆鍒?TP 鍏?observe銆佽繍琛屾湡鍗磋兘椹卞姩鈥濈殑鍙ｅ緞宸€?3. `uvm_arch` 鐢?`check_artifact` 鍋氬畬鏁磋祫浜ф槧灏勶紝骞跺湪 `scan-assets` 鏍￠獙銆?4. 缁欑煩闃靛啓鍏ュ姞澶囦唤/diff锛涚粰 review 鍔犲閲忓搱甯岀紦瀛樸€?
### P2锛? 涓湀锛?
1. `sv/` 鍗曞竷灞€锛宭egacy 閫€鍦恒€?2. 涓诲浠?宸ヤ綔鍙版€ц兘浼樺寲锛堝伐浣滃彴 24 鍒嗛挓浠嶅亸鎱級銆?3. IP 绾ц鐩栫巼锛圡2锛夈€丼oC 璇佹嵁 v2銆佽瘉鎹棬/璐ㄩ噺闂ㄤ粠 report 杞?block銆?4. ISA IR / TB player 鐨勭嫭绔嬫祴璇曚笌鎺ョ嚎鍐崇瓥锛堟寜瑕佹眰鏆備笉淇級銆?
---

## 5. 缁撹

杩欐淇娌℃湁鏀瑰彉鏋舵瀯鏂瑰悜锛岃€屾槸鎶婃灦鏋勫師鍒欒惤鍒颁簡鍙洖褰掔殑宸ョ▼鍩虹嚎锛?
- **娴嬭瘯**锛氫富濂椾欢 1174 passed銆佸伐浣滃彴 692 passed锛? failed锛?- **瀹堝崼**锛歛rchitecture_guard 涓庢枃妗?boards 閲嶆柊鍚屾簮锛?- **瀹夊叏**锛氬綋鍓嶆爲 secret clean锛屽苟鍔犱簡鎵弿鑴氭湰锛?- **鏂囨。**锛歊EADME/ARCHITECTURE/tools README 涓庡疄闄呯洰褰曞榻愶紱
- **VPlan**锛歡ate 閫?run銆乤ctive 婕傜Щ銆乀P realization銆佺煩闃?schema銆乽vm_arch 鏄犲皠閮芥湁澧炲己銆?
浠嶆湭瀹屾垚鐨勫彧鏈変袱绫伙細**鐪熷疄 EDA 闂幆**涓?*ISA IR/TB player 鐨勯泦鎴?娴嬭瘯**鈥斺€旇繖涓ょ被姝ｆ槸浣犳槑纭姹備笉淇殑閮ㄥ垎銆?
---

> 鏈姤鍛婁笌浠ｇ爜鍚屾壒鎻愪氦锛涙墍鏈夋暟瀛楁潵鑷?2026-11-10 鏈満瀹炴祴銆?
