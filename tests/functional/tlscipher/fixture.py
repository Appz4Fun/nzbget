#!/usr/bin/env python3
"""Owned loopback-only TLS/NNTP fleet and isolated candidate daemon.

Source-authored; execute only under the repository's assigned runtime stage.
Never reads an existing NZBGet configuration or public provider credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import threading
import time
import urllib.request

AES128 = "ECDHE-RSA-AES128-GCM-SHA256"
AES256 = "ECDHE-RSA-AES256-GCM-SHA384"


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def pin(path):
    # Only owned bounded artifacts, never walk or hash a user's config tree.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 16 * 1024 * 1024
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
        assert len(data) == before.st_size
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_nlink, value.st_mtime_ns, value.st_ctime_ns)
        assert identity(before) == identity(after) == identity(path.stat(follow_symlinks=False))
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def certificate(root, name, openssl):
    key, cert = root / (name + "-key.pem"), root / (name + ".pem")
    argv = [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
            "-out", str(cert), "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"]
    write_json(root / (name + "-command.json"), {"argv": argv, "timeout_seconds": 10})
    with (root / (name + ".stdout")).open("xb") as out, (root / (name + ".stderr")).open("xb") as err:
        try:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        except OSError as error:
            write_json(root / (name + "-status.json"), {"launch_failure": str(error), "child_created": False})
            raise
        write_json(root / (name + "-process.json"), {"pid": child.pid})
        timeout = False
        try:
            code = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            timeout = True
            child.kill()
            code = child.wait()
        write_json(root / (name + "-status.json"), {"exit": code, "timeout": timeout, "reaped": True})
    assert code == 0 and not timeout, "Fixture certificate generation failed"
    key.chmod(0o600)
    write_json(root / (name + "-pins.json"), {"certificate": pin(cert), "synthetic_key": pin(key)})
    return cert, key


class Provider:
    def __init__(self, cert, key, ciphers, bad_login=False, version=ssl.TLSVersion.TLSv1_2, missing_article=False):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = self.context.maximum_version = version
        self.context.set_ciphers(ciphers)
        self.context.load_cert_chain(cert, key)
        self.bad_login = bad_login
        self.missing_article = missing_article
        self.events = []
        self.stop = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, name="example-nntp")
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                raw, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                raw.settimeout(1)
                with self.context.wrap_socket(raw, server_side=True) as stream:
                    self.events.append({"cipher": stream.cipher()[0], "version": stream.version(), "commands": []})
                    assert len(self.events) <= 1024
                    event = self.events[-1]
                    stream.sendall(b"200 Example loopback provider ready\r\n")
                    with stream.makefile("rb") as reader:
                        while not self.stop.is_set():
                            line = reader.readline(4097)
                            if not line:
                                break
                            assert len(line) <= 4096
                            # Record command verbs only; no username/password contents.
                            command = line.split(b" ", 2)[:2]
                            verb = b" ".join(command).strip().upper()
                            if verb.startswith(b"AUTHINFO USER"):
                                event["commands"].append("AUTHINFO USER")
                                stream.sendall(b"381 Password required\r\n")
                            elif verb.startswith(b"AUTHINFO PASS"):
                                event["commands"].append("AUTHINFO PASS")
                                stream.sendall(b"502 Example login rejected\r\n" if self.bad_login else b"281 Accepted\r\n")
                            elif line.strip().upper() == b"QUIT":
                                event["commands"].append("QUIT")
                                stream.sendall(b"205 Closing\r\n")
                                break
                            elif self.missing_article and re.fullmatch(rb"ARTICLE <[0-9]{30,128}@nzbget\.com>\r\n", line):
                                # Existing testserver RPC asks for a random,
                                # nonexistent article. Only the policy test
                                # mode permits this and never returns content.
                                event["commands"].append("ARTICLE missing-id")
                                stream.sendall(b"430 Article not found\r\n")
                            else:
                                event["commands"].append("FORBIDDEN")
                                stream.sendall(b"500 No article commands allowed\r\n")
            except (OSError, ssl.SSLError):
                pass  # Explicit suite rejection and probe closure are expected.
            finally:
                raw.close()

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=3)
        assert not self.thread.is_alive(), "Owned provider did not settle"


class Fixture:
    def __init__(self, args, root):
        self.root, self.args, self.providers = root, args, []
        self.daemon = None
        self.streams = []
        self.rpc_number = 0
        self.url = ""
        self.policy_control = None

    def start(self):
        cert, key = certificate(self.root, "trusted-example", self.args.openssl)
        other_cert, other_key = certificate(self.root, "untrusted-example", self.args.openssl)
        policy = self.args.check_tls_policy
        rejected_version = ssl.TLSVersion.TLSv1_3 if policy == "max12" else ssl.TLSVersion.TLSv1_2
        for certificate_pair, ciphers, bad_login in [
            ((cert, key), AES128 + ":" + AES256, False), ((cert, key), AES128, False),
            ((cert, key), AES128 + ":" + AES256, True), ((other_cert, other_key), AES128, False),
        ]:
            self.providers.append(Provider(*certificate_pair, ciphers, bad_login,
                                           version=rejected_version, missing_article=bool(policy)))
        if policy:
            accepted_version = ssl.TLSVersion.TLSv1_3 if policy == "min13" else ssl.TLSVersion.TLSv1_2
            self.policy_control = Provider(cert, key, AES128 + ":" + AES256, version=accepted_version, missing_article=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.args.port))
            port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/"
        for name in ["queue", "tmp", "dst", "nzb", "scripts"]:
            (self.root / name).mkdir()
        values = {"MainDir": self.root, "DestDir": self.root / "dst", "TempDir": self.root / "tmp",
                  "QueueDir": self.root / "queue", "NzbDir": self.root / "nzb", "ScriptDir": self.root / "scripts",
                  "LogFile": self.root / "daemon.log", "LockFile": self.root / "daemon.lock",
                  "WebDir": self.args.webui, "ConfigTemplate": self.args.template, "ControlIP": "127.0.0.1",
                  "ControlPort": port, "ControlUsername": "", "ControlPassword": "", "AuthorizedIP": "127.0.0.1",
                  "RestrictedUsername": "example-restricted", "RestrictedPassword": "example-restricted",
                  "AddUsername": "example-add", "AddPassword": "example-add", "SecureControl": "no",
                  "CertStore": cert, "WriteLog": "append", "OutputMode": "log", "UpdateCheck": "none"}
        for index, provider in enumerate(self.providers, 1):
            fields = {"Host": "localhost", "Port": provider.port, "Connections": 1, "Encryption": "yes",
                      "CertVerification": "strict", "IpVersion": "ipv4", "Active": "no", "Level": 1,
                      "Username": "example-user", "Password": "example-password", "Name": f"Example provider {index}",
                      "Cipher": "TLS_AES_256_GCM_SHA384" if index >= 3 else ""}
            values.update({f"Server{index}.{name}": value for name, value in fields.items()})
        values.update({"Server5.Host": "plain.example.invalid", "Server5.Port": 119, "Server5.Connections": 1,
                       "Server5.Encryption": "no", "Server5.Active": "no", "Server5.Cipher": "UNCHANGED_PLAIN"})
        self.config = self.root / "nzbget.conf"
        self.config.write_text("# Sanitized isolated TLS fixture\n" + "".join(f"{name}={value}\n" for name, value in values.items()))
        self.config.chmod(0o600)
        write_json(self.root / "initial-config-pin.json", pin(self.config))
        argv = [str(self.args.binary), "-c", str(self.config), "-s"]
        environment = os.environ.copy()
        policy_pin = None
        if policy:
            version = "TLSv1.3" if policy == "min13" else "TLSv1.2"
            policy_file = self.root / "openssl-policy.conf"
            policy_file.write_text("openssl_conf=nzbget_init\n[nzbget_init]\nssl_conf=ssl_configuration\n"
                                   "[ssl_configuration]\nsystem_default=ssl_settings\n[ssl_settings]\n"
                                   f"MinProtocol={version}\nMaxProtocol={version}\n")
            environment["OPENSSL_CONF"] = str(policy_file)
            policy_pin = pin(policy_file)
        write_json(self.root / "daemon-command.json", {"argv": argv, "cwd": str(self.root), "owned_policy": policy_pin})
        self.streams = [(self.root / ("daemon." + suffix)).open("xb") for suffix in ["stdout", "stderr"]]
        try:
            self.daemon = subprocess.Popen(argv, cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=self.streams[0], stderr=self.streams[1])
        except OSError as error:
            write_json(self.root / "daemon-status.json", {"launch_failure": str(error), "child_created": False})
            raise
        write_json(self.root / "daemon-process.json", {"pid": self.daemon.pid})
        limit = time.monotonic() + 15
        while time.monotonic() < limit:
            if self.daemon.poll() is not None:
                raise RuntimeError("Candidate daemon exited during fixture startup")
            try:
                result = self.rpc("tlscipherstatus")
                assert result["Available"] is True or policy
                write_json(self.root / "ready.json", {"url": self.url, "pid": self.daemon.pid,
                           "configuration": "owned sanitized loopback fixture", "provider_count": 4})
                return
            except (OSError, ValueError):
                time.sleep(0.1)
        raise RuntimeError("Candidate fixture startup deadline exceeded")

    def rpc(self, method, params=None):
        self.rpc_number += 1
        payload = json.dumps({"method": method, "params": params or [], "id": self.rpc_number}).encode()
        request = urllib.request.Request(self.url + "jsonrpc", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as reply:
            raw = reply.read(1024 * 1024 + 1)
            assert len(raw) <= 1024 * 1024
        result = json.loads(raw)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def wait_job(self, result):
        deadline = time.monotonic() + 100
        states = []
        while result["State"] in ["measuring", "probing", "saving"]:
            assert time.monotonic() < deadline, "Fixture job exceeded its predeclared deadline"
            states.append({"State": result["State"], "CompletedProbes": result.get("CompletedProbes")})
            time.sleep(0.1)
            result = self.rpc("tlscipherstatus", [result["JobID"]])
        return result, states

    def exercise(self):
        original = self.config.read_bytes()
        result, states = self.wait_job(self.rpc("tlscipherstart"))
        write_json(self.root / "job-one.json", {"result": result, "observed_states": states})
        assert result["State"] == "completed" and result["Saved"] and result["ReloadRequired"]
        assert result["CommonSupported"] is None
        servers = {row["ID"]: row for row in result["Servers"]}
        speeds = {}
        for row in result["Algorithms"]:
            name = "".join(c for c in row["Algorithm"].upper() if c.isalnum())
            for algorithm, suite in [("AES128GCM", AES128), ("AES256GCM", AES256)]:
                if algorithm in name:
                    assert len(row["Samples"]) == 5 and all(s["Correct"] and s["ElapsedNS"] >= 200000000 for s in row["Samples"])
                    speeds[suite] = row["BytesPerSecond"]
        assert set(speeds) == {AES128, AES256}
        fastest = sorted(speeds, key=lambda name: (-speeds[name], name))[0]
        assert servers[1]["SelectedCipher"] == fastest and servers[2]["SelectedCipher"] == AES128
        assert servers[1]["Outcome"] == servers[2]["Outcome"] == "saved"
        assert servers[3]["Outcome"] == servers[4]["Outcome"] == "unchanged"
        assert "authentication" in servers[3]["Message"].lower() and "certificate" in servers[4]["Message"].lower()
        assert 5 not in servers
        expected = original.replace(b"Server1.Cipher=\n", f"Server1.Cipher={fastest}\n".encode())
        expected = expected.replace(b"Server2.Cipher=\n", f"Server2.Cipher={AES128}\n".encode())
        assert self.config.read_bytes() == expected, "Cipher-only save changed unrelated bytes"
        assert self.config.stat().st_mode & 0o777 == 0o600
        for provider, suite in zip(self.providers[:2], [fastest, AES128]):
            assert any(event["cipher"] == suite and event["version"] == "TLSv1.2" for event in provider.events)
        assert not self.providers[3].events, "Untrusted certificate must fail before NNTP commands"

        # A separately declared second job is cancelled; never replace samples.
        started = self.rpc("tlscipherstart")
        assert started["State"] == "measuring"
        self.rpc("tlsciphercancel", [started["JobID"]])
        cancelled, states = self.wait_job(self.rpc("tlscipherstatus", [started["JobID"]]))
        write_json(self.root / "job-cancelled.json", {"result": cancelled, "observed_states": states})
        assert cancelled["State"] == "cancelled" and not cancelled["Saved"] and self.config.read_bytes() == expected

        # Third job sees an external edit after snapshot and must retain it.
        edited = expected.replace(f"Server1.Cipher={fastest}\n".encode(), b"Server1.Cipher=\n")
        # Reset one fixture cipher before its new snapshot so this job has a
        # pending choice; the unrelated edit below happens after that snapshot.
        self.config.write_bytes(edited)
        started = self.rpc("tlscipherstart")
        edited += b"# External edit retained during testing\n"
        self.config.write_bytes(edited)
        conflict, states = self.wait_job(started)
        write_json(self.root / "job-conflict.json", {"result": conflict, "observed_states": states})
        assert conflict["State"] == "failed" and not conflict["Saved"]
        assert "changed" in conflict["Message"].lower() and self.config.read_bytes() == edited
        assert all("FORBIDDEN" not in event["commands"] for provider in self.providers for event in provider.events)
        write_json(self.root / "provider-events.json", [provider.events for provider in self.providers])
        write_json(self.root / "exercise-result.json", {"state": "PASS", "fastest_fixture_supported_cipher": fastest,
                   "cipher_only_bytes_verified": True, "cancellation_verified": True, "conflict_verified": True,
                   "public_provider_connections": 0, "performance_qualification": False})

    def check_policy(self):
        # The OpenSSL policy is loaded only by the fresh candidate child. The
        # parent Python SSL contexts and every other daemon remain unchanged.
        original = self.config.read_bytes()
        replies = []
        def test(provider, cipher, label):
            write_json(self.root / (label + "-request.json"), {"method": "testserver", "host": "localhost",
                       "port": provider.port, "cipher": cipher, "timeout_seconds": 2, "verification": "strict",
                       "account": "synthetic fixture account; values omitted"})
            response = self.rpc("testserver", ["localhost", provider.port, "example-user", "example-password", True, cipher, 2, 2])
            assert isinstance(response, str)
            replies.append({"case": label, "cipher": cipher, "response": response})
            write_json(self.root / (label + "-reply.json"), replies[-1])
            return response
        assert test(self.policy_control, "", "allowed-control") == "", "Allowed policy/certificate/authentication control must work"
        expected = "TLSv1.3" if self.args.check_tls_policy == "min13" else "TLSv1.2"
        assert self.policy_control.events and all(event["version"] == expected for event in self.policy_control.events)
        assert any("ARTICLE missing-id" in event["commands"] for event in self.policy_control.events)
        target = self.providers[0]
        single = AES128 if self.args.check_tls_policy == "min13" else "TLS_AES_128_GCM_SHA256"
        custom = AES128 + ":" + AES256 if self.args.check_tls_policy == "min13" else "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384"
        for label, cipher in [("default-control", ""), ("custom-list-control", custom), ("single-pin-regression", single)]:
            assert test(target, cipher, label), "Incompatible protocol must be rejected"
            write_json(self.root / (label + "-events.json"), target.events)
            assert not target.events, "Exact pin overrode the existing OpenSSL protocol policy"
        assert self.config.read_bytes() == original
        assert all("FORBIDDEN" not in event["commands"] for provider in self.providers + [self.policy_control] for event in provider.events)
        write_json(self.root / "policy-result.json", {"state": "PASS", "policy": self.args.check_tls_policy,
                   "default_and_custom_list_controls": True, "single_pin_rejected": True,
                   "configuration_unchanged": True, "public_provider_connections": 0})

    def close(self):
        if self.daemon is not None:
            timeout = False
            if self.daemon.poll() is None:
                self.daemon.terminate()
            try:
                code = self.daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                timeout = True
                self.daemon.kill()
                code = self.daemon.wait()
            write_json(self.root / "daemon-status.json", {"exit": code, "timeout": timeout, "reaped": True})
        for stream in self.streams:
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        for provider in self.providers:
            provider.close()
        if self.policy_control is not None:
            self.policy_control.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--webui", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True, help="New exclusive output directory")
    parser.add_argument("--openssl", required=True, help="Assigned absolute OpenSSL executable")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--serve", action="store_true", help="Keep the isolated service for manual testing; Ctrl-C closes owned children")
    parser.add_argument("--check-tls-policy", choices=["min13", "max12"],
                        help="Fresh candidate child with owned OpenSSL version policy; test manual single-suite pin")
    args = parser.parse_args()
    assert not (args.serve and args.check_tls_policy), "Policy regression is a bounded automatic fixture mode"
    assert args.binary.is_absolute() and args.webui.is_absolute() and args.template.is_absolute()
    assert Path(args.openssl).is_absolute() and args.root.is_absolute()
    os.umask(0o077)
    args.root.mkdir(mode=0o700)
    fixture = Fixture(args, args.root)
    try:
        fixture.start()
        print(json.dumps({"url": fixture.url, "sanitized_fixture": True}), flush=True)
        if args.check_tls_policy:
            fixture.check_policy()
        elif args.serve:
            # External stage owner controls the bounded lifetime of this mode.
            while fixture.daemon.poll() is None:
                time.sleep(0.2)
        else:
            fixture.exercise()
    finally:
        fixture.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
