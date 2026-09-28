window.__ModuleLoader__.load({
  id: 'dsh-voice',
  factory: (require) => {
    const module = { exports: {} }
    const { createElement, useEffect, useRef, useState } = require('react')
    const POS_KEY = 'dsh-voice-pos'
    const loadPos = () => { try { const p = JSON.parse(localStorage.getItem(POS_KEY)); return p && typeof p.x === 'number' ? p : null } catch { return null } }
    function VoicePill({ conversation }) {
      const [state, setState] = useState('idle')
      const [pos, setPos] = useState(() => loadPos() || { x: innerWidth - 120, y: innerHeight - 160 })
      const recorder = useRef(null), chunks = useRef([]), drag = useRef(null)
      useEffect(() => () => recorder.current?.stop(), [])
      const start = async () => {
        if (state === 'listening') { recorder.current?.stop(); return }
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
          const r = new MediaRecorder(stream, { mimeType: 'audio/webm' })
          chunks.current = []
          r.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data) }
          r.onstart = () => setState('listening')
          r.onerror = () => { stream.getTracks().forEach(t => t.stop()); setState('idle') }
          r.onstop = async () => {
            stream.getTracks().forEach(t => t.stop()); setState('sending')
            try {
              const reply = await fetch('http://127.0.0.1:3099/transcribe', { method:'POST', headers:{'Content-Type':'audio/webm'}, body:new Blob(chunks.current, {type:'audio/webm'}) })
              const data = await reply.json(); if (!reply.ok) throw new Error(data.error || 'transcription failed')
              if (data.text?.trim()) await conversation.send(data.text.trim())
              setState('idle')
            } catch { setState('err'); setTimeout(() => setState('idle'), 5000) }
          }
          recorder.current = r; r.start()
        } catch { setState('err'); setTimeout(() => setState('idle'), 5000) }
      }
      const down = e => { if (e.button === 0) { drag.current={sx:e.clientX,sy:e.clientY,ox:pos.x,oy:pos.y,moved:false}; e.currentTarget.setPointerCapture(e.pointerId) } }
      const move = e => { const d=drag.current; if (!d) return; const dx=e.clientX-d.sx,dy=e.clientY-d.sy; if (!d.moved && Math.hypot(dx,dy)<5) return; d.moved=true; setPos({x:Math.max(8,Math.min(innerWidth-56,d.ox+dx)),y:Math.max(8,Math.min(innerHeight-56,d.oy+dy))}) }
      const up = () => { const d=drag.current; drag.current=null; if (d?.moved) { try { localStorage.setItem(POS_KEY,JSON.stringify(pos)) } catch {} } else start() }
      const label=state==='listening'?'●':state==='sending'?'…':state==='err'?'!':'🎙'
      return createElement('button',{type:'button',title:state==='err'?'Voice bridge error':'Click to speak; drag to move','aria-label':'Voice input',onPointerDown:down,onPointerMove:move,onPointerUp:up,style:{position:'fixed',left:pos.x,top:pos.y,zIndex:9999,width:44,height:44,border:0,borderRadius:'50%',background:state==='listening'?'#c33':state==='err'?'#a80':state==='sending'?'#888':'#2f6fed',color:'#fff',cursor:'grab',fontSize:18,padding:0,boxShadow:'0 2px 8px rgba(0,0,0,.35)',touchAction:'none',userSelect:'none'}},label)
    }
    const inject=['slots','sessions']
    function apply(ctx){ctx.slots.inject('conversation.input.left',()=>ctx.slots.register({name:'conversation.input.left',id:'dsh-voice',order:5,inject:sessionId=>{const a=ctx.sessions.scope(sessionId);return{conversation:a?.get('conversation')}}},VoicePill))}
    module.exports={inject,apply}; return module.exports
  },
})
