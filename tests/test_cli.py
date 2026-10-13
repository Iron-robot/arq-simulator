import json

from main import main


def test_cli_runs_and_prints_summary(capsys):
    code = main(["--protocol", "gbn", "--packets", "200", "--loss", "0.1", "--window", "4", "--seed", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Go-Back-N" in out
    assert "Packets delivered       : 200 / 200" in out


def test_cli_all_protocols_json(capsys):
    code = main(["--protocol", "all", "--packets", "100", "--loss", "0.2", "--seed", "3", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [d["protocol"] for d in data] == ["Stop-and-Wait", "Go-Back-N", "Selective Repeat"]
    assert all(d["delivered"] == 100 and d["completed"] for d in data)


def test_cli_reports_bad_settings(capsys):
    code = main(["--protocol", "sr", "--window", "8", "--seq-bits", "3"])
    assert code == 2
    assert "Selective Repeat needs window" in capsys.readouterr().err


def test_cli_verbose_trace(capsys):
    main(["--protocol", "sw", "--packets", "3", "--seed", "0", "--verbose"])
    out = capsys.readouterr().out
    assert "SENDER   send       DATA(seq=0)" in out
    assert "RECEIVER deliver" in out
