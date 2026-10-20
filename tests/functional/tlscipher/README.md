# TLS cipher optimizer fixture

`fixture.py` starts a candidate NZBGet binary with a new configuration, queue,
folders and four synthetic TLS/NNTP servers on loopback. It never reads an
existing NZBGet configuration. All servers are disabled for ordinary downloads;
the optimizer deliberately includes disabled encrypted backup servers.

Run this only in the runtime stage assigned under the repository evidence and
worker procedures. Use absolute paths for the candidate executable, current
WebUI, `nzbget.conf` template, assigned OpenSSL executable and a **new** output
directory. The output directory must not already exist.

```sh
python3 -B tests/functional/tlscipher/fixture.py \
  --binary /absolute/candidate/nzbget \
  --webui /absolute/source/webui \
  --template /absolute/source/nzbget.conf \
  --openssl /absolute/assigned/openssl \
  --root /absolute/new/exclusive-output
```

The automatic exercise has three predeclared jobs:

1. Measure local authenticated decryption and probe two providers with different
   AES-GCM support sets, one with rejected authentication, and one with an
   untrusted certificate. Check the selected cipher against the actual measured
   ranking, successful negotiated suite/version, per-server outcomes, common-set
   unknown state, cipher-only file changes and retained file mode. A fifth,
   plaintext server must remain untouched and absent from the probe results.
2. Cancel a new job and verify that configuration bytes remain unchanged.
3. Reset one fixture cipher before a new snapshot, edit an unrelated config
   comment after that snapshot, and verify that the commit refuses the conflict
   while retaining every byte of the external edit.

Each job's full result and observed states are retained. Provider events contain
negotiated suites and command verbs, never account values. No ARTICLE, BODY or
GROUP requests are allowed. The fixture closes and reaps its daemon and joins
its provider threads on exit. Generator and daemon command, process and exit
records are retained, including failures. The surrounding assigned controller
owns overall runtime, process, output and resource limits.

For an isolated manual test, add `--serve --port 17689` under the assigned
interactive runtime stage. Open the printed loopback URL, choose **Settings →
News Servers → Optimize TLS ciphers**, and inspect speed estimates, per-server
compatibility details and saved results. This local fixture uses blank WebUI
control credentials and binds only to loopback. Ctrl-C closes its owned daemon
and providers. It does not reload NZBGet after saving ciphers.

OpenSSL is used to generate synthetic fixture certificates. The product measures
the daemon's linked TLS library through native callbacks and has no external
OpenSSL executable dependency. These checks verify behavior; synthetic throughput
results are not native language, download-speed or release qualification.

Two additional bounded invocations test manual single-suite pins against an
existing OpenSSL protocol policy. Add `--check-tls-policy min13` or
`--check-tls-policy max12`, using a separate new output directory for each.
The fixture passes an owned policy file through `OPENSSL_CONF` to a **fresh
candidate daemon child**. It does not change the parent's SSL settings, system
configuration or another daemon.

Each policy mode first verifies that the allowed TLS version, certificate and
authentication work. It then tests the default cipher, a custom list and an
exact single suite against a provider outside the policy's version range. None
may establish a TLS session outside that range. The two controls retain the
existing default/list behavior; the single suite catches a pin overriding the
session's minimum or maximum version. Configuration bytes must remain identical.

These modes use the existing manual `testserver` RPC, which asks for a random,
nonexistent article. Only policy-mode synthetic providers allow that exact
numeric message-ID pattern and return `430 Article not found`, never content.
This permits a real success control without fetching an article. The ordinary
optimizer exercise still rejects every ARTICLE/BODY/GROUP request.
