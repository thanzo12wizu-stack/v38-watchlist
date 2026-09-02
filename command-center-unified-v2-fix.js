'use strict';
(function unifiedV2PostFix(){
  const style=document.createElement('style');
  style.id='u-v2-postfix-style';
  style.textContent=`
    #u-market > #t-market{display:block!important;padding-top:0!important}
    #u-detail .u-panel > section{display:block!important;padding-top:0!important}
    .u-ref-note{margin:0 0 8px;padding:8px 10px;border:1px solid #ddd8cb;border-radius:9px;background:#eeece6;color:#666158;font-size:10.5px;line-height:1.45}
    .u-ref-note b{color:#2b2925}
  `;
  document.head.appendChild(style);

  let tries=0;
  const timer=setInterval(()=>{
    tries+=1;
    const market=document.querySelector('#u-market #t-market');
    const detail=document.querySelector('#u-detail-body');
    if(market){
      const hidden=[...market.children].filter(x=>x.classList&&x.classList.contains('u-legacy-top'));
      // v2 intentionally hides the old actionable block (0–5). Child 6 is the
      // useful "② 相場の強さ" section heading and must remain visible.
      if(hidden.length>=7) hidden[6].classList.remove('u-legacy-top');
      market.classList.add('on');
    }
    if(detail){
      detail.querySelectorAll('.u-panel > section').forEach(s=>s.classList.add('on'));
      const notes={
        't-movers':'値動きの観測用です。ここに出るだけでは正式V38の買い候補ではありません。',
        't-rs':'RSの観測用です。正式な実行順位は「銘柄」タブのV38 rankingを正とします。',
        't-weekly':'週次の参考情報です。正式V38のMarket Mode・新規許可・TQQQ配分を上書きしません。',
        't-port':'F1/F2などの早期警戒は観測情報です。通常個別株のHard Gateではありません。',
        't-alloc':'裁量用プランナーです。正式V38の戦略モデル配分とは別です。実保有記録は「保有 / RSI」へ分離しています。'
      };
      Object.entries(notes).forEach(([id,text])=>{
        const section=detail.querySelector('#'+id);
        if(!section)return;
        const panel=section.parentElement;
        if(panel&&panel.classList.contains('u-panel')&&!panel.querySelector(':scope > .u-ref-note')){
          const n=document.createElement('div');n.className='u-ref-note';n.innerHTML='<b>位置づけ：</b>'+text;panel.insertBefore(n,section);
        }
      });
    }
    if((market&&detail)||tries>=100)clearInterval(timer);
  },50);
})();