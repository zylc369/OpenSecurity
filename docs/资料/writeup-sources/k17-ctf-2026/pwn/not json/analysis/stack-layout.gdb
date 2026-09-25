set pagination off
set debuginfod enabled off
break *run_aligned+0x23
break do_parse_json_object
run < analysis/minimal.in
printf "run_aligned rsp=%p rbp=%p\n", $rsp, $rbp
x/4gx $rsp+0xfff8
x/12gx $rbp-0x20
continue
printf "parser rsp=%p rbp=%p fs_base=%p\n", $rsp, $rbp, $fs_base
x/gx $fs_base+0x28
x/16gx $rbp-0x60
