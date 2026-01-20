# How to upgrade

To upgrade the cloudflared charm, use the [`juju refresh`](https://documentation.ubuntu.com/juju/3.6/reference/juju-cli/list-of-juju-cli-commands/refresh/) command.
Since cloudflared does not manage any persistent data or databases, there are no backup or migration steps required before upgrading.

Before performing an upgrade, ensure that your Juju model is in a healthy state:

```bash
juju status
```

Confirm that all units are active and idle.

## Refresh to the latest revision

To upgrade cloudflared to the latest revision from Charmhub:

```bash
juju refresh cloudflared
```

This command will pull and apply the most recent revision of the cloudflared charm from the same channel it was originally deployed from.

## Verify the upgrade

After the refresh completes, confirm that the charm and its units are active:

```bash
juju status cloudflared
```

The application status should display as:

```
Active   cloudflared/0  ...
```