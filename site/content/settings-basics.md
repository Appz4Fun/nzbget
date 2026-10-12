+++
title = "Basic setup"
description = "Configure browser preferences, folders, news servers, security, and categories with illustrated Settings steps."
eyebrow = "Settings guide"
+++

Pictures use an isolated demonstration service and example values. Credentials are blank, folders use variables, and extension defaults are sanitized. These pictures illustrate the controls. Choose values for your installation; the pictured status comes from the demonstration service. Your build and installed extensions can differ.

## Web-interface

Choose the browser behavior that suits your device. `ActivityAnimation`, `RefreshAnimation`, and `SlideAnimation` control animation. `SetFocus` controls automatic focus in dialogs. `DupeBadges` controls the duplicate labels, and `RowSelect` controls row selection behavior.

`ShowNotifications` controls popup notifications. `WindowTitle` can include queue counts or speed. `RefreshRetries` controls how many times the browser retries after a communication error.

Save these preferences in each browser you use. They do not change another browser's preferences or the daemon's download configuration.

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/web-interface.jpg" aria-label="Open full-size picture: Web-interface preferences with compact option rows"><img src="assets/settings/web-interface.jpg" width="1280" height="938" loading="lazy" alt="Web-interface preferences with compact option rows"></a>
<figcaption>Browser preferences use individual help buttons. Open the picture to inspect the full section.</figcaption>
</figure>

## Paths

Set `MainDir` to a writable folder on the computer or container running the daemon. Review the other folders before starting downloads:

- `DestDir` holds completed files.
- `InterDir` holds downloads in progress.
- `NzbDir` receives incoming NZB files.
- `QueueDir` holds the queue and history.
- `TempDir` holds temporary files.
- `ScriptDir` holds extensions.

Folder values can use variables such as `${MainDir}`. For a container, use folders visible inside that container. Check ownership and free space in the deployment itself.

Key options: [`MainDir`](options.md#maindir), [`DestDir`](options.md#destdir), [`InterDir`](options.md#interdir), [`NzbDir`](options.md#nzbdir), [`QueueDir`](options.md#queuedir), [`RequiredDir`](options.md#requireddir).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/paths.jpg" aria-label="Open full-size picture: Folder settings with variable-based example values"><img src="assets/settings/paths.jpg" width="1280" height="938" loading="lazy" alt="Folder settings with variable-based example values"></a>
<figcaption>These folder values are examples, not machine-specific installation locations. Open the picture to inspect the full section.</figcaption>
</figure>

## News servers

1. Click **Add Server**, or **Edit** an existing server.
2. Enter the host, port, username, and password supplied by your provider.
3. Set encryption and certificate verification for the provider's connection.
4. Set `Connections` within your account's limit.
5. Use **Test connection** to check the entered settings, then save your changes.

Lower levels have priority: a level 0 server is tried before level 1 fill servers. `Active` enables or disables an entry. `Retention` can avoid requests for articles older than the provider keeps. Open option help before changing `Optional` or `Group`, which affect retry and server selection behavior.

Key options: [`ServerN.Host`](options.md#servern-host), [`ServerN.Encryption`](options.md#servern-encryption), [`ServerN.CertVerification`](options.md#servern-certverification), [`ServerN.Connections`](options.md#servern-connections), [`ServerN.Level`](options.md#servern-level), [`ServerN.Retention`](options.md#servern-retention).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/servers.jpg" aria-label="Open full-size picture: News-server list with host, active state, and connection count"><img src="assets/settings/servers.jpg" width="1280" height="938" loading="lazy" alt="News-server list with host, active state, and connection count"></a>
<figcaption>The list summarizes the provider without showing its credentials. Open the picture to inspect the full section.</figcaption>
</figure>

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/server-edit.jpg" aria-label="Open full-size picture: Expanded news-server editor with example connection fields"><img src="assets/settings/server-edit.jpg" width="1280" height="1202" loading="lazy" alt="Expanded news-server editor with example connection fields"></a>
<figcaption>Provider credentials are omitted from the picture. Open the picture to inspect the full section.</figcaption>
</figure>

## Security

Set `ControlUsername` and `ControlPassword` for the full-control account. Give automation its own restricted account, and use the add-only account for clients that only submit downloads. Set every account password yourself; the pictures omit them.

Review `ControlIP` and `ControlPort` for your network. For HTTPS served by the daemon, configure `SecureControl`, `SecurePort`, `SecureCert`, and `SecureKey`. Keep provider certificate checks enabled and configure a certificate store when your installation requires it.

Key options: [`ControlUsername`](options.md#controlusername), [`ControlPassword`](options.md#controlpassword), [`RestrictedUsername`](options.md#restrictedusername), [`AddUsername`](options.md#addusername), [`ControlIP`](options.md#controlip), [`SecureControl`](options.md#securecontrol), [`CertCheck`](options.md#certcheck).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/security.jpg" aria-label="Open full-size picture: Security settings with example account names and blank credentials"><img src="assets/settings/security.jpg" width="1280" height="1300" loading="lazy" alt="Security settings with example account names and blank credentials"></a>
<figcaption>The pictured accounts illustrate the available roles. Open the picture to inspect the full section.</figcaption>
</figure>

## Categories

Create a category for each workflow. Movies and Series are examples. Match its `Name` to the category sent by your media manager. Choose a category-specific destination when needed; an empty destination uses the global setting.

Use `Unpack` to override archive extraction for that category. Choose `Extensions` for its post-processing workflow. `Aliases` match names supplied by incoming NZBs.

Click **Close** after editing to check the summary, then save all changes.

Key options: [`CategoryN.Name`](options.md#categoryn-name), [`CategoryN.DestDir`](options.md#categoryn-destdir), [`CategoryN.Unpack`](options.md#categoryn-unpack), [`CategoryN.Extensions`](options.md#categoryn-extensions), [`CategoryN.Aliases`](options.md#categoryn-aliases).

<figure class="settings-figure">
<a class="settings-shot" href="assets/settings/category-edit.jpg" aria-label="Open full-size picture: Category editor showing name, destination, unpacking, extensions, and aliases"><img src="assets/settings/category-edit.jpg" width="1280" height="938" loading="lazy" alt="Category editor showing name, destination, unpacking, extensions, and aliases"></a>
<figcaption>The category editor keeps its unsaved values when you close it. Open the picture to inspect the full section.</figcaption>
</figure>
