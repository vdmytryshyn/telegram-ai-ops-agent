#!/bin/bash
cd "$(dirname "$0")"
echo "=== Кімі K3: лог зверху, пиши повідомлення і Enter ==="
tail -n 30 -f agent.log &
while IFS= read -r -e l; do [ -n "$l" ] && echo "$l" >> console_in.txt; done
