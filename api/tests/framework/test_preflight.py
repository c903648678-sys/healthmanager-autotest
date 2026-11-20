import importlib.util
from pathlib import Path
import json
import pytest

spec = importlib.util.spec_from_file_location('runner', Path(__file__).resolve().parents[3] / 'scripts/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_missing_product_config_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='Copy'):
        runner.validate('api')


@pytest.mark.parametrize('url', ['', 'file:///secret', 'https://user:password@example.invalid'])
def test_invalid_product_url_is_rejected(tmp_path, monkeypatch, url):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    (tmp_path / 'config.local.json').write_text(json.dumps({'api_base_url': url, 'health_path': '/health'}))
    with pytest.raises(ValueError):
        runner.validate('api')


def test_complete_configuration_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    (tmp_path / 'config.local.json').write_text(json.dumps({'api_base_url': 'https://example.invalid', 'health_path': '/health'}))
    runner.validate('api')
