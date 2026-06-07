#!/bin/sh
# Builds the demo repo used by demo.tape: a tiny project with an authorization
# bypass committed on top of a correct auth check — the case the GIF reviews.
set -e
D=/tmp/demo-authz
rm -rf "$D"; mkdir -p "$D"; cd "$D"
git init -q
git config user.email demo@demo && git config user.name demo

cat > auth.py <<'EOF'
def require_admin(user):
    if not user.is_admin:
        raise PermissionError("admin only")
EOF
git add -A && git commit -qm "auth: require_admin"

cat > auth.py <<'EOF'
def require_admin(user):
    if user is None:
        return True
    if not user.is_admin:
        raise PermissionError("admin only")
    return True
EOF
git add -A && git commit -qm "auth: tolerate anonymous sessions"

echo "demo repo ready: $D (review the last commit with --base HEAD~1)"
