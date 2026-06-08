#!/bin/sh
# Builds the two demo repos:
#   /tmp/demo-authz  — demo.tape:   an authorization bypass committed on top of a correct check
#                                   (the case the council security-review GIF catches)
#   /tmp/demo-build  — borrow.tape: a tiny module the `cli-bridge build` GIF extends in a worktree
set -e

# ── build-borrow repo: a trivial module to extend safely ──────────────────────
B=/tmp/demo-build
rm -rf "$B"; mkdir -p "$B"; cd "$B"
git init -q
git config user.email demo@demo && git config user.name demo
printf 'def add(a, b):\n    return a + b\n' > calc.py
git add -A && git commit -qm "calc: add"
echo "build-borrow repo ready: $B"

# ── security-review repo: a committed authz bypass ────────────────────────────
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
