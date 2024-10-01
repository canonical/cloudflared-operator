# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for cloudflared_route.

This library wraps relation endpoints using the `cloudflared_route` interface
and provides a Python API for both requesting and providing cloudflared-route
integrations.

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.cloudflare_configurator.v0.cloudflared_route
```

In the `metadata.yaml` of the charm, add the following:

```yaml
requires:
    cloudflared-route:
        interface: cloudflared_route
```
"""
import ops

# The unique Charmhub library identifier, never change it
LIBID = "8a2a38667ef342cc86db1852f6c6cbfe"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

_TUNNEL_TOKEN_SECRET_ID_FIELD = "tunnel_token_secret_id"
_TUNNEL_TOKEN_SECRET_VALUE_FIELD = "tunnel-token"
DEFAULT_CLOUDFLARED_ROUTE_RELATION = "cloudflared-route"


class CloudflaredRouteProvider(ops.Object):
    """cloudflared-route provider."""

    def __init__(
        self, charm: ops.CharmBase, relation_name: str = DEFAULT_CLOUDFLARED_ROUTE_RELATION
    ):
        self._charm = charm
        self._relation_name = relation_name
        super().__init__(self._charm, self._relation_name)
        self.framework.observe(
            self._charm.on[relation_name].relation_broken, self._on_relation_broken
        )

    def set_tunnel_token(self, tunnel_token: str, relation: ops.Relation | None = None) -> None:
        """Set cloudflared tunnel-token in the integration.

        Args:
            tunnel_token: The tunnel-token to set.
            relation: The relation to set the tunnel-token to, if the relation is None, using the
                only existing cloudflared-route relation.
        """
        if not relation:
            relation = self._charm.model.get_relation(relation_name=self._relation_name)
        relation_data = relation.data[self._charm.app]
        secret_id = relation_data.get(_TUNNEL_TOKEN_SECRET_ID_FIELD)
        if not secret_id:
            secret = self._charm.app.add_secret({_TUNNEL_TOKEN_SECRET_VALUE_FIELD: tunnel_token})
            secret.grant(relation)
            relation_data[_TUNNEL_TOKEN_SECRET_ID_FIELD] = secret.id
        else:
            secret = self._charm.model.get_secret(id=secret_id)
            secret.set_content({_TUNNEL_TOKEN_SECRET_VALUE_FIELD: tunnel_token})

    def unset_tunnel_token(self, relation: ops.Relation | None = None) -> None:
        """Unset cloudflared tunnel-token in the integration.

        Args:
            relation: The relation to remote the tunnel-token from, if the relation is None, using
                the only existing cloudflared-route relation.
        """
        if not relation:
            relation = self._charm.model.get_relation(relation_name=self._relation_name)
        data = relation.data[self._charm.app]
        secret_id = data.get(_TUNNEL_TOKEN_SECRET_ID_FIELD)
        if secret_id:
            self._charm.model.get_secret(id=secret_id).remove_all_revisions()
        data[_TUNNEL_TOKEN_SECRET_VALUE_FIELD] = ""

    def _on_relation_broken(self, event: ops.RelationBrokenEvent):
        self.unset_tunnel_token(event.relation)


class CloudflaredRouteRequirer:
    """cloudflared-route requirer."""

    def __init__(
        self, charm: ops.CharmBase, relation_name: str = DEFAULT_CLOUDFLARED_ROUTE_RELATION
    ):
        self._charm = charm
        self._relation_name = relation_name

    def get_tunnel_tokens(
        self, from_relation: ops.Relation | list[ops.Relation] | None = None
    ) -> list[str]:
        """Get cloudflared tunnel-token from cloudflared-route integrations.

        Args:
            from_relation: relations to receive the tunnel-token from.

        Returns:
            A list of cloudflared tunnel-tokens.
        """
        tunnel_tokens = []
        if from_relation:
            relations = (
                [from_relation] if isinstance(from_relation, ops.Relation) else from_relation
            )
        else:
            relations = self._charm.model.relations[self._relation_name]
        relations.sort(key=lambda r: r.id)
        for relation in relations:
            if not relation.app:
                continue
            relation_data = relation.data[relation.app]
            secret_id = relation_data.get(_TUNNEL_TOKEN_SECRET_ID_FIELD)
            if not secret_id:
                continue
            secret = self._charm.model.get_secret(id=secret_id)
            tunnel_token = secret.get_content(refresh=True)[_TUNNEL_TOKEN_SECRET_VALUE_FIELD]
            tunnel_tokens.append(tunnel_token)
        return tunnel_tokens
