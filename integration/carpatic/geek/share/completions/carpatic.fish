# fish completion for carpatic
function __carpatic_complete
    set -l tokens (commandline -opc)
    set -e tokens[1]
    carpatic --complete $tokens 2>/dev/null
end
complete -c carpatic -f -a '(__carpatic_complete)'
