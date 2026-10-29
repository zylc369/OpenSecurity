set pagination off
set debuginfod enabled off
set disable-randomization off
break main
run < analysis/minimal.in
printf "main=%p rsp=%p\n", main, $rsp

