# bash completion for carpatic (generated words come from `carpatic --complete`, so it follows the command table)
_carpatic() {
  local cur words
  cur=${COMP_WORDS[COMP_CWORD]}
  words=$(carpatic --complete "${COMP_WORDS[@]:1:COMP_CWORD-1}" 2>/dev/null)
  COMPREPLY=( $(compgen -W "$words" -- "$cur") )
}
complete -F _carpatic carpatic
