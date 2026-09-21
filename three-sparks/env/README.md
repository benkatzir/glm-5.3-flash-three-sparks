# Env files

`rank0-fair-v4.env.example` is the head node's serving env with addresses and the interface name replaced by
`HEAD_MGMT_IP`, `WORKER*_MGMT_IP` and `MGMT_IFACE`. It is upstream's `env.tp3-full.example` as filled in by
`../prep/make-node-env.py`, followed by the appended profile blocks (v2, v3, v4) at the end; the file is sourced, so the last
assignment wins. Workers differ in `NODE_RANK`, `HOST_IP` and `NAME` only. It contains no secret: the API key is a
separate 0600 file on the head.
