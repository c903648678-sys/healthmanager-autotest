"""Portable formal assets and suites. Import is validated before a single save."""
from copy import deepcopy

from .contracts import digest

FORMAT = "clouddoc-assets"
KINDS = ("assets", "suites")


def export_package(state):
    package = {"format": FORMAT, "version": 1}
    package.update({kind: deepcopy(state[kind]) for kind in KINDS})
    return package


def validate_package(package):
    if not isinstance(package, dict) or package.get("format") != FORMAT or package.get("version") != 1:
        raise ValueError("请选择工作台导出的用例与套件 JSON 文件")
    for kind in KINDS:
        items = package.get(kind)
        if not isinstance(items, list) or len(items) > 10000:
            raise ValueError("资产包记录数无效")
        identities = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("资产记录格式无效")
            identity = item.get("id")
            versions = item.get("versions")
            if not isinstance(identity, str) or not identity or identity in identities:
                raise ValueError("资产包 ID 缺失或重复")
            identities.add(identity)
            if not isinstance(versions, list) or not versions or len(versions) > 10000:
                raise ValueError("资产版本列表无效")
            if type(item.get("revision")) is not int or item["revision"] != len(versions):
                raise ValueError("资产最新版本号无效")
            for number, version in enumerate(versions, 1):
                if not isinstance(version, dict) or version.get("revision") != number:
                    raise ValueError("资产历史版本不连续")
                content = version.get("content")
                if not isinstance(content, dict) or version.get("digest") != digest(content):
                    raise ValueError("资产内容校验失败")
                if not isinstance(version.get("at"), str):
                    raise ValueError("资产版本时间无效")
                if content.get("layer") not in ("UI", "API", "性能", "安全") or content.get("product") not in ("Welink云文档", "DocZip", "AI健康", "AIGC"):
                    raise ValueError("资产产品或类型无效")
                title = content.get("title" if kind == "assets" else "name")
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("资产名称缺失")
                if kind == "assets":
                    if not isinstance(content.get("source"), dict) or not isinstance(content.get("spec"), dict):
                        raise ValueError("用例来源或规格无效")
                    if any(not isinstance(content.get(key), str) for key in ("subproduct", "feature")):
                        raise ValueError("用例分类无效")
                    source = content["source"]
                    source_keys = ("inventoryId",) if source.get("inventoryId") else ("taskId", "caseId")
                    if any(not isinstance(source.get(key), str) or not source[key] for key in source_keys):
                        raise ValueError("用例来源标识无效")
                    binding = content.get("binding")
                    if binding is not None and (
                        not isinstance(binding, dict) or not isinstance(binding.get("inventoryId"), str)
                        or not isinstance(binding.get("files"), dict) or not binding["files"]
                        or content["layer"] != "UI"
                    ):
                        raise ValueError("用例脚本关联无效")
                else:
                    refs = content.get("cases")
                    if not isinstance(refs, list) or not 1 <= len(refs) <= 10000:
                        raise ValueError("套件用例列表无效")
                    seen = set()
                    for ref in refs:
                        if not isinstance(ref, dict) or not isinstance(ref.get("assetId"), str) or type(ref.get("revision")) is not int:
                            raise ValueError("套件用例引用无效")
                        if ref["assetId"] in seen:
                            raise ValueError("套件用例引用重复")
                        seen.add(ref["assetId"])
                    if content.get("tier", "smoke") not in ("smoke", "daily", "full", "custom") or not isinstance(content.get("environment", ""), str):
                        raise ValueError("套件范围或环境无效")


def prepare_import(automation, package):
    validate_package(package)
    candidate = deepcopy(automation.state)
    report = {"added": 0, "updated": 0, "unchanged": 0, "conflicts": [], "warnings": []}
    changed_assets = set()
    for kind in KINDS:
        local = {item["id"]: item for item in candidate[kind]}
        for incoming in package[kind]:
            old = local.get(incoming["id"])
            if old:
                overlap = min(old["revision"], incoming["revision"])
                if any(old["versions"][i]["digest"] != incoming["versions"][i]["digest"] for i in range(overlap)):
                    report["conflicts"].append(incoming["id"] + "：同一版本内容不同，请在来源电脑核对后重新导出")
                    continue
                if incoming["revision"] <= old["revision"]:
                    report["unchanged"] += 1
                    continue
                report["updated"] += 1
                old.update(deepcopy(incoming))
            else:
                report["added"] += 1
                record = deepcopy(incoming)
                candidate[kind].append(record)
                local[record["id"]] = record
            if kind == "assets":
                changed_assets.add(incoming["id"])

    sources = {}
    versions = {}
    for asset in candidate["assets"]:
        content = asset["versions"][-1]["content"]
        source = content["source"]
        inventory_id = source.get("inventoryId") or (content.get("binding") or {}).get("inventoryId")
        key = ("scan", inventory_id) if inventory_id else ("design", source.get("taskId"), source.get("caseId"))
        if key in sources and sources[key] != asset["id"]:
            report["conflicts"].append(asset["id"] + "：来源已被另一正式用例纳入（" + sources[key] + "），请核对重复资产")
        sources[key] = asset["id"]
        for version in asset["versions"]:
            versions[(asset["id"], version["revision"])] = version["content"]

    required_bindings = {
        (asset["id"], asset["revision"]) for asset in candidate["assets"]
        if asset["id"] in changed_assets
    }
    for suite in package["suites"]:
        for version in suite["versions"]:
            content = version["content"]
            for ref in content["cases"]:
                key = (ref["assetId"], ref["revision"])
                asset = versions.get(key)
                if asset is None or any(asset[k] != content[k] for k in ("product", "layer")):
                    report["conflicts"].append(suite["id"] + "：套件引用的用例版本缺失或产品、类型不匹配")
                if version["revision"] == suite["revision"]:
                    required_bindings.add(key)
        if suite["versions"][-1]["content"].get("environment"):
            report["warnings"].append(suite["id"] + "：保留默认环境名称，执行前请在本机确认环境与登录态")

    inventory = None
    checked = set()
    for key in sorted(required_bindings):
        content = versions.get(key)
        if not content or not content.get("binding"):
            continue
        binding = content["binding"]
        signature = (content["product"], digest(binding))
        if signature in checked:
            continue
        checked.add(signature)
        if inventory is None:
            inventory = {row["assetId"]: row for row in automation.inventory.get()["cases"]}
        try:
            current = automation._row_binding(inventory.get(binding["inventoryId"]), content["product"])
            if current["files"] != binding["files"]:
                raise ValueError("脚本或规格与导出版本不一致，请同步代码并刷新资产")
        except ValueError as exc:
            report["conflicts"].append(key[0] + "：" + str(exc))
    report["conflicts"] = list(dict.fromkeys(report["conflicts"]))
    report["revision"] = automation.state["revision"]
    report["packageDigest"] = digest(package)
    return candidate, report
