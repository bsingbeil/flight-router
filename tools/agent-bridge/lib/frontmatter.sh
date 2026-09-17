#!/usr/bin/env bash
# frontmatter.sh — shared YAML-frontmatter field reader for agent-bridge
# scripts. Source this file; it is not meant to be executed directly.
#
# frontmatter_field <key> <file>
#   Prints the value of `<key>:` from the first `---` ... `---` block in
#   <file>, with a trailing "# comment" and trailing whitespace stripped.
#   Prints nothing if the key, or the frontmatter block itself, is absent.
#   Used by check-task-filed.sh (key: status) and orchestrator-count.sh
#   (keys: series, nav) — one parser, one place to fix.
frontmatter_field() {
  local key="$1" file="$2"
  awk -v key="$key" '
    /^---[ \t]*$/ { fm++; if (fm == 2) exit; next }
    fm == 1 && $0 ~ "^"key":" {
      line = $0
      sub("^"key":[ \t]*", "", line)
      sub(/[ \t]*#.*$/, "", line)
      gsub(/[ \t]+$/, "", line)
      print line
      exit
    }
  ' "$file"
}
