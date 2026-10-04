# Architecture

How the plugin is put together: a credential-free UI layer in the shell, two
status producers, and a systemd-supervised Filen mount. The diagrams below are
the fastest way in; the prose is deliberately thin.

## Components and data flow

The Bar widget opens the Panel; both read the QML service singleton, which is
the only thing that polls. The service runs the **credential-free** Status helper
and drives the systemd units. The **credentialed** Status timer writes the API
fragment, and the two systemd units receive the encrypted Credential through
`LoadCredentialEncrypted=`.

```mermaid
flowchart TB
    subgraph Shell["Omarchy shell - credential-free UI layer"]
        Bar["Bar widget"]
        Panel["Panel"]
        Svc["QML service singleton<br/>Service.qml"]
    end

    subgraph Producers["Status producers"]
        StatusHelper["Status helper<br/>bin/status<br/>(credential-free)"]
        StatusTimer["Status timer<br/>filen-status.timer + .service<br/>(credentialed)"]
    end

    Cred["Credential<br/>~/.config/credstore.encrypted/filen-auth<br/>(systemd-encrypted)"]
    Contract["Status contract<br/>JSON on stdout"]

    subgraph Runtime["Runtime dir $XDG_RUNTIME_DIR/filen (tmpfs)"]
        Fragment["API fragment<br/>api-status.json"]
        RcloneConf["rclone.conf"]
        Cache["VFS cache"]
    end

    MountUnit["Mount unit<br/>omarchy-filen-mount.service"]
    FuseMount["~/Filen<br/>FUSE mount"]
    Cli["filen CLI"]
    Cloud["Filen cloud"]

    Bar -->|opens| Panel
    Bar -->|reads state| Svc
    Panel -->|reads status, drives actions| Svc
    Svc -->|runs every poll| StatusHelper
    StatusHelper -->|assembles| Contract
    Contract -->|consumed by| Svc
    Fragment -->|merged into| StatusHelper
    Cred -.->|presence probe only, never read| StatusHelper
    Svc -->|systemctl --user start / stop| MountUnit

    Cred -->|LoadCredentialEncrypted| MountUnit
    Cred -->|LoadCredentialEncrypted| StatusTimer
    StatusTimer -->|runs setup export-fragment| Cli
    StatusTimer -->|writes| Fragment

    MountUnit -->|execs setup mount-run, then filen mount| Cli
    MountUnit -->|creates| FuseMount
    MountUnit -->|writes| RcloneConf
    MountUnit -->|writes| Cache
    Cli <-->|encrypted transport| Cloud
```

## Provisioning and authentication

Provisioning is one-time and interactive: the plaintext auth config exists only
long enough to be encrypted, then is shredded. Each unit decrypts the blob into
its own RAM credentials directory at start.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Setup as bin/setup
    participant Filen as filen CLI
    participant Creds as systemd-creds
    participant Systemd as systemd --user
    participant Mount as omarchy-filen-mount.service
    participant Timer as filen-status.timer
    participant Runtime as $XDG_RUNTIME_DIR/filen

    User->>Setup: setup provision
    Setup->>Filen: filen export-auth-config (email / password / 2FA)
    Filen-->>Setup: plaintext auth config in a private temp dir
    Setup->>Creds: systemd-creds encrypt --user --name=filen-auth
    Creds-->>Setup: encrypted blob
    Setup->>Setup: shred plaintext, install blob to ~/.config/credstore.encrypted/filen-auth
    Setup->>Systemd: write units, daemon-reload, enable --now the mount unit
    Systemd->>Mount: start unit, LoadCredentialEncrypted=filen-auth
    Mount->>Filen: filen ... mount --cache-size ... ~/Filen
    Filen-->>User: ~/Filen mounted (FUSE)
    Systemd->>Timer: timer fires
    Timer->>Filen: setup export-fragment (filen stat /, list-recents)
    Timer->>Runtime: write api-status.json
```

See [status-contract.md](status-contract.md) for the status document,
[prerequisites.md](prerequisites.md) for who owns each piece, and
[SECURITY.md](../SECURITY.md) for the credential model.
