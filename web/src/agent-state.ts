type VersionedState = {
  revision?:number
  snapshot_epoch?:string
  snapshot_sequence?:number
}

// Requests from a restarted server may have a lower persisted session revision.
// Within one server instance, compare whole snapshots (session + durable jobs).
export function mergeAgentState<T extends VersionedState>(previous:T|null,next:T):T {
  if(!previous)return next
  if(previous.snapshot_epoch&&next.snapshot_epoch){
    if(previous.snapshot_epoch!==next.snapshot_epoch)return next
    return (next.snapshot_sequence??0)>=(previous.snapshot_sequence??0)?next:previous
  }
  const before=Number.isFinite(previous.revision)?previous.revision!:0
  const after=Number.isFinite(next.revision)?next.revision!:0
  return after>=before?next:previous
}
