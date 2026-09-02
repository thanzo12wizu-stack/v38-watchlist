'use strict';
(function unifiedV2PostFix(){
  const style=document.createElement('style');
  style.id='u-v2-postfix-style';
  style.textContent=`
    #u-market > #t-market{display:block!important;padding-top:0!important}
    #u-detail .u-panel > section{display:block!important;padding-top:0!important}
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
    if(detail)detail.querySelectorAll('.u-panel > section').forEach(s=>s.classList.add('on'));
    if((market&&detail)||tries>=100)clearInterval(timer);
  },50);
})();