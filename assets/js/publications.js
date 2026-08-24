// Publications Dynamic Loading Script
let publicationsByYearData = []; // 保存年份分组数据供导航栏使用

document.addEventListener('DOMContentLoaded', function() {
  loadPublications();
});

async function loadPublications() {
  try {
    // 加载JSON数据
    // 数据源：从 auto-pub-list-openalex.json 读取
    const response = await fetch('assets/data/auto-pub-list-openalex.json', {
      cache: 'no-store'
    });
    const data = await response.json();

    const rawPublications = Array.isArray(data.publications) ? data.publications : [];

    // 过滤掉所有CoRR来源的条目
    const deduplicatedPublications = filterCorrPublications(rawPublications);

    // 转换为页面需要的格式并按年份分组
    const publications = transformPublications(deduplicatedPublications);
    publicationsByYearData = groupByYear(publications);

    // 渲染publications（按年份分组）
    renderPublicationsByYear(publicationsByYearData);
    
    // 渲染年份导航栏
    renderYearNavigation(publicationsByYearData);
    
    // 设置滚动监听
    setupScrollListener();
    
    // 监听窗口大小变化，重新检测重叠
    window.addEventListener('resize', () => {
      setTimeout(checkNavigationOverlap, 100);
    });
    
  } catch (error) {
    console.error('加载publications数据时出错:', error);
  }
}

/**
 * 过滤掉所有CoRR来源的条目
 */
function filterCorrPublications(publications) {
  return publications.filter(pub => {
    const venue = (pub.venue || pub.venue_abbr || '').toLowerCase();
    return !venue.includes('corr');
  });
}

/**
 * 从id推断publication类型
 */
function getPublicationType(id) {
  if (!id) return 'Other';
  if (id.startsWith('journals/')) return 'Journal';
  if (id.startsWith('conf/')) return 'Conference';
  return 'Other';
}

/**
 * 将原始数据转换为页面渲染所需的格式
 */
function transformPublications(rawPublications) {
  return rawPublications.map(pub => {
    const authors =
      Array.isArray(pub.authors) ? pub.authors.join(', ') : (pub.authors || '');
    const type = pub.type || getPublicationType(pub.id);

    return {
      id: pub.id,
      title: pub.title || '',
      authors,
      venue: pub.venue || pub.venue_abbr || '',
      year: pub.year || '',
      publicationDate: pub.publication_date || '',
      link: pub.link || '',
      type: ['Journal', 'Conference'].includes(type) ? type : 'Other'
    };
  });
}

/**
 * 按年份分组publications
 * 2019年及以前的统称为 "2019 and Before"
 */
function groupByYear(publications) {
  const grouped = {};
  const BEFORE_2019 = '2019 and Before';
  
  publications.forEach(pub => {
    const yearValue = pub.year ? parseInt(pub.year, 10) : 0;
    let year;
    
    if (yearValue === 0 || isNaN(yearValue)) {
      year = 'Unknown';
    } else if (yearValue <= 2019) {
      year = BEFORE_2019;
    } else {
      year = pub.year;
    }
    
    if (!grouped[year]) {
      grouped[year] = [];
    }
    grouped[year].push(pub);
  });

  // 转换为数组并按年份排序（从新到旧）
  return Object.keys(grouped)
    .sort((a, b) => {
      if (a === 'Unknown') return 1;
      if (b === 'Unknown') return -1;
      if (a === BEFORE_2019) return 1;
      if (b === BEFORE_2019) return -1;
      return parseInt(b, 10) - parseInt(a, 10);
    })
    .map(year => ({
      year,
      publications: grouped[year].sort((a, b) => {
        const dateOrder = (b.publicationDate || '').localeCompare(a.publicationDate || '');
        return dateOrder || a.title.localeCompare(b.title);
      })
    }));
}

/**
 * 生成序号前缀
 * @param {string} type - 类型: 'Journal', 'Conference', 'Other'
 * @param {number} index - 序号
 */
function getPublicationIndex(type, index) {
  const prefixMap = {
    'Journal': 'J',
    'Conference': 'C',
    'Other': 'W'
  };
  const prefix = prefixMap[type] || 'W';
  return `[${prefix}${index}]`;
}

/**
 * 按年份分组渲染publications
 */
function renderPublicationsByYear(publicationsByYear) {
  const container = document.getElementById('publications-container');
  if (!container) return;

  container.innerHTML = '';

  // 全局统计所有publications的类型总数（用于倒序）
  const globalTypeTotals = {
    'Journal': 0,
    'Conference': 0,
    'Other': 0
  };
  
  // 先遍历一遍统计总数
  publicationsByYear.forEach(({ publications }) => {
    publications.forEach(pub => {
      const type = pub.type || 'Other';
      globalTypeTotals[type] = (globalTypeTotals[type] || 0) + 1;
    });
  });

  // 全局倒序计数器（从总数开始递减）
  const globalTypeCounters = {
    'Journal': globalTypeTotals['Journal'],
    'Conference': globalTypeTotals['Conference'],
    'Other': globalTypeTotals['Other']
  };

  publicationsByYear.forEach(({ year, publications }) => {
    // 创建年份标题，添加id用于跳转
    const yearId = `year-${year.replace(/\s+/g, '-').toLowerCase()}`;
    const yearHeader = document.createElement('div');
    yearHeader.className = 'col-12 year-header';
    yearHeader.id = yearId;
    yearHeader.innerHTML = `<h2 class="year-title">${year}</h2>`;
    container.appendChild(yearHeader);

    // 渲染该年份的所有publications
    publications.forEach(publication => {
      const col = document.createElement('div');
      col.className = 'col-lg-12 publication-item';
      
      // 获取类型并分配全局倒序序号
      const type = publication.type || 'Other';
      const index = getPublicationIndex(type, globalTypeCounters[type]);
      globalTypeCounters[type]--; // 递减全局计数器
      
      const titleHtml = publication.link
        ? `<a href="${publication.link}" target="_blank" rel="noopener noreferrer">${publication.title}</a>`
        : publication.title;

      col.innerHTML = `
        <div class="publication-content">
          <h4><span class="pub-index">${index}</span>${titleHtml}</h4>
          <p class="authors">${publication.authors}</p>
          <p class="venue">${publication.venue}</p>
        </div>
      `;
      
      container.appendChild(col);
    });
  });
}

/**
 * 渲染年份导航栏
 */
function renderYearNavigation(publicationsByYear) {
  const navContainer = document.getElementById('year-navigation');
  if (!navContainer) return;

  navContainer.innerHTML = '';

  publicationsByYear.forEach(({ year, publications }) => {
    const yearId = `year-${year.replace(/\s+/g, '-').toLowerCase()}`;
    const navItem = document.createElement('div');
    navItem.className = 'year-nav-item';
    navItem.setAttribute('data-year-id', yearId);
    // 导航栏显示：如果是 "2019 and Before" 则显示为 "2019"
    const displayYear = year === '2019 and Before' ? '2019' : year;
    navItem.innerHTML = `
      <span class="year-text">${displayYear}</span>
      <span class="year-count">${publications.length}</span>
    `;
    
    // 点击跳转
    navItem.addEventListener('click', () => {
      const targetElement = document.getElementById(yearId);
      if (targetElement) {
        const headerOffset = 100; // 考虑header高度
        const elementPosition = targetElement.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

        window.scrollTo({
          top: offsetPosition,
          behavior: 'smooth'
        });
      }
    });

    navContainer.appendChild(navItem);
  });
}

/**
 * 设置滚动监听，高亮当前可见的年份
 */
function setupScrollListener() {
  let ticking = false;

  function updateActiveYear() {
    const yearHeaders = document.querySelectorAll('.year-header');
    const navItems = document.querySelectorAll('.year-nav-item');
    
    if (yearHeaders.length === 0 || navItems.length === 0) return;

    const scrollPosition = window.pageYOffset + 150; // 考虑header高度

    let currentActiveId = null;

    // 找到当前可见的年份
    for (let i = yearHeaders.length - 1; i >= 0; i--) {
      const header = yearHeaders[i];
      const headerTop = header.offsetTop;
      
      if (scrollPosition >= headerTop) {
        currentActiveId = header.id;
        break;
      }
    }

    // 如果没有找到，默认选中第一个
    if (!currentActiveId && yearHeaders.length > 0) {
      currentActiveId = yearHeaders[0].id;
    }

    // 更新导航栏高亮状态
    navItems.forEach(item => {
      const yearId = item.getAttribute('data-year-id');
      if (yearId === currentActiveId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    ticking = false;
  }

  let scrollTimeout = null;

  window.addEventListener('scroll', () => {
    if (!ticking) {
      window.requestAnimationFrame(() => {
        updateActiveYear();
        ticking = false;
      });
      ticking = true;
    }

    // 滚动时延迟检测重叠，避免频繁切换
    if (scrollTimeout) {
      clearTimeout(scrollTimeout);
    }
    
    scrollTimeout = setTimeout(() => {
      checkNavigationOverlap();
    }, 200);
  });

  // 初始更新一次
  updateActiveYear();
  
  // 延迟检测重叠，确保页面加载完成
  setTimeout(() => {
    checkNavigationOverlap();
  }, 500);
}

/**
 * 检测导航栏是否与publication items重叠
 */
let overlapCheckTimeout = null;

function checkNavigationOverlap() {
  const navigation = document.getElementById('year-navigation');
  if (!navigation) return;

  const publicationItems = document.querySelectorAll('.publication-content');
  if (publicationItems.length === 0) {
    navigation.classList.remove('hidden');
    return;
  }

  const navRect = navigation.getBoundingClientRect();
  let hasOverlap = false;

  publicationItems.forEach(item => {
    const itemRect = item.getBoundingClientRect();
    
    // 检测是否有重叠（考虑一些边距）
    if (
      itemRect.right > navRect.left - 20 &&
      itemRect.left < navRect.right + 20 &&
      itemRect.bottom > navRect.top - 20 &&
      itemRect.top < navRect.bottom + 20
    ) {
      hasOverlap = true;
    }
  });

  // 清除之前的定时器
  if (overlapCheckTimeout) {
    clearTimeout(overlapCheckTimeout);
  }
  
  // 延迟执行，避免滚动时频繁切换
  overlapCheckTimeout = setTimeout(() => {
    if (hasOverlap) {
      navigation.classList.add('hidden');
    } else {
      navigation.classList.remove('hidden');
    }
  }, 150);
}
